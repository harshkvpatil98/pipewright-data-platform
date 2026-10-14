"""Alerts on a dataset's measures (adoption-readiness A8, Y5).

Through HTTP: new data records its measures (an upload, not only a
workflow); an alert made past its line says so at once; it says so once
while the measure stays past it and again when it comes back; a change
alert measures against the time before; and the worker sends each event,
after commit, to the project's people and its alert targets.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from service_governance.audit_words import summarise
from service_notifications.models import UserNotification
from service_observability import alerts
from service_observability.models import DatasetMetric, MetricAlertEvent
from service_observability.service import record_dataset_metrics
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    db = factory()
    db.add(User(username="owner", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.commit()
    db.close()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = client.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    dataset = client.post(f"/api/v1/projects/{project}/samples/orders").json()["dataset"]
    yield {"api": client, "db": factory, "project": project, "dataset": dataset}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json()


def _alerts(world) -> str:
    return f"/api/v1/projects/{world['project']}/datasets/{world['dataset']['id']}/metric-alerts"


def _record(world, **changes) -> None:
    """New data with these measures, as a run would write them."""
    session = world["db"]()
    profile = {"row_count": world["dataset"]["row_count"], "completeness_score": 99.0, **changes}
    record_dataset_metrics(
        session, project_id=uuid.UUID(world["project"]), dataset_id=uuid.UUID(world["dataset"]["id"]), profile=profile
    )
    session.commit()
    session.close()


def _events(world) -> list[MetricAlertEvent]:
    session = world["db"]()
    rows = session.scalars(select(MetricAlertEvent).order_by(MetricAlertEvent.created_at)).all()
    session.close()
    return list(rows)


def test_an_upload_records_its_measures(world) -> None:
    session = world["db"]()
    rows = session.scalars(select(DatasetMetric).where(DatasetMetric.metric_key == "row_count")).all()
    session.close()
    assert [row.value for row in rows] == [float(world["dataset"]["row_count"])], "not only workflows record"


def test_an_alert_says_so_once_while_crossed_and_again_when_it_comes_back(world, monkeypatch) -> None:
    api, rows = world["api"], world["dataset"]["row_count"]
    made = _ok(api.post(_alerts(world), json={"metric_key": "row_count", "condition": "above", "threshold": 10}), 201)
    assert made["state"] == "crossed", "made past its line, it says so now, not at the next run"
    assert made["sentence"] == "Alert when the row count is above 10"
    [crossed] = _events(world)
    assert crossed.kind == "crossed" and crossed.sent_at is None
    assert crossed.message == f"In Sample orders, the row count is {rows}, above the 10 its alert allows."

    _record(world)  # still above: nothing new
    assert len(_events(world)) == 1

    _record(world, row_count=4)
    assert [event.kind for event in _events(world)] == ["crossed", "cleared"]
    listed = _ok(api.get(_alerts(world)))
    assert listed["items"][0]["state"] == "ok" and listed["items"][0]["last_value"] == 4
    assert [event["kind"] for event in listed["events"]] == ["cleared", "crossed"]

    # The worker sends each, once, to the project's people and its alert targets.
    sent_out: list[dict] = []
    monkeypatch.setattr(
        "service_notifications.external_dispatch.dispatch_external_notifications",
        lambda db, **event: sent_out.append(event),
    )
    session = world["db"]()
    assert alerts.send_due(session) == 2
    assert alerts.send_due(session) == 0, "sent once"
    notes = session.scalars(select(UserNotification).order_by(UserNotification.created_at)).all()
    session.close()
    assert [event["event_type"] for event in sent_out] == ["metric_alert", "metric_alert"]
    assert [event["level"] for event in sent_out] == ["warning", "info"]
    assert sent_out[0]["title"] == "Sample orders: the row count is above 10"
    assert {note.title for note in notes} == {event["title"] for event in sent_out}


def test_a_change_alert_measures_against_the_time_before(world) -> None:
    api, rows = world["api"], world["dataset"]["row_count"]
    made = _ok(api.post(_alerts(world), json={"metric_key": "row_count", "condition": "changes_by", "threshold": 20}), 201)
    assert made["state"] == "ok" and _events(world) == [], "one reading: no change to judge yet"

    _record(world, row_count=rows + 1)
    assert _events(world) == []
    _record(world, row_count=(rows + 1) // 2)
    [event] = _events(world)
    assert event.kind == "crossed" and event.previous_value == rows + 1
    assert "changed by" in event.title and "more than the 20% its alert allows" in event.message
    _record(world, row_count=(rows + 1) // 2)
    assert [e.kind for e in _events(world)] == ["crossed", "cleared"], "no change since: back within"


def test_a_column_alert_and_the_refusals_in_words(world) -> None:
    api = world["api"]
    made = _ok(api.post(_alerts(world), json={
        "metric_key": "null_percentage", "column_name": "amount", "condition": "above", "threshold": 50,
    }), 201)
    assert made["sentence"] == "Alert when the null rate of 'amount' is above 50.0%"
    assert made["state"] == "ok"

    def refused(body: dict) -> str:
        answer = api.post(_alerts(world), json=body)
        assert answer.status_code == 400, answer.text
        return answer.json()["detail"]

    assert "does not record" in refused({"metric_key": "vibes", "condition": "above", "threshold": 1})
    assert "Choose the column" in refused({"metric_key": "mean_value", "condition": "above", "threshold": 1})
    assert "no column “colour”" in refused(
        {"metric_key": "mean_value", "column_name": "colour", "condition": "above", "threshold": 1}
    )
    assert "takes no column" in refused(
        {"metric_key": "row_count", "column_name": "amount", "condition": "above", "threshold": 1}
    )
    assert "between 0 and 100" in refused({"metric_key": "completeness_score", "condition": "below", "threshold": 120})
    assert "more than 0%" in refused({"metric_key": "row_count", "condition": "changes_by", "threshold": 0})

    alert = made["id"]
    off = _ok(api.patch(f"{_alerts(world)}/{alert}", json={"enabled": False}))
    assert off["enabled"] is False
    assert api.delete(f"{_alerts(world)}/{alert}").status_code == 204
    assert _ok(api.get(_alerts(world)))["items"] == []


def test_the_audit_log_names_alert_changes() -> None:
    base = "/api/v1/projects/3f1d2c3b-0000-4000-8000-000000000001/datasets/3f1d2c3b-0000-4000-8000-000000000002"
    alert = "3f1d2c3b-0000-4000-8000-000000000003"
    assert summarise("POST", f"{base}/metric-alerts") == "added an alert on a dataset's measure"
    assert summarise("PATCH", f"{base}/metric-alerts/{alert}") == "changed an alert on a dataset's measure"
    assert summarise("DELETE", f"{base}/metric-alerts/{alert}") == "removed an alert on a dataset's measure"
