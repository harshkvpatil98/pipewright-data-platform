"""A project's activity in one stream (adoption-readiness A8, Y6).

Through HTTP: a change, a run, a comment, an alert and an incident each
appear once, newest first, as a sentence with who and a link; the stream
filters by kind, pages backwards with `next_before`, and shows only
changes that happened (refusals stay in the audit log).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from service_observability import incidents
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    # A file and a pool, as in production: the audit log writes on a session of
    # its own, and one connection shared by every thread would let the request's
    # clean-up roll that write back.
    engine = create_engine(f"sqlite:///{tmp_path / 'activity.db'}", connect_args={"check_same_thread": False})
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
    db.add(User(username="ann", display_name="Ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.commit()
    db.close()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = client.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    yield {"api": client, "db": factory, "project": project}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json()


def _activity(world, **query) -> dict:
    return _ok(world["api"].get(f"/api/v1/projects/{world['project']}/activity", params=query))


def test_everything_that_happened_in_one_stream(world) -> None:
    api, project = world["api"], world["project"]
    dataset = _ok(api.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    recipe = _ok(api.post(f"/api/v1/projects/{project}/datasets/{dataset['id']}/pipelines", json={
        "name": "Clean orders", "steps_json": [{"step_type": "remove_duplicates", "config": {}}],
    }), 201)["id"]
    _ok(api.post(f"/api/v1/projects/{project}/pipelines/{recipe}/run"), 200)
    _ok(api.post(f"/api/v1/projects/{project}/discussion", json={
        "target_type": "dataset", "target_id": dataset["id"], "body": "These look   doubled\nsince Monday.",
    }), 201)
    _ok(api.post(f"/api/v1/projects/{project}/datasets/{dataset['id']}/metric-alerts", json={
        "metric_key": "row_count", "condition": "above", "threshold": 10,
    }), 201)
    session = world["db"]()
    incidents.report(
        session, project_id=uuid.UUID(project), fingerprint="test:late", title="Orders are late",
        summary="Nothing since yesterday.", source_kind="freshness", severity="high",
    )
    session.commit()
    session.close()

    items = _activity(world)["items"]
    moments = [datetime.fromisoformat(item["at"].replace("Z", "+00:00")) for item in items]
    assert moments == sorted(moments, reverse=True), "newest first"
    by_kind = {kind: [item for item in items if item["kind"] == kind] for kind in ("changes", "runs", "comments", "alerts", "incidents")}

    created = next(item for item in by_kind["changes"] if item["sentence"] == "Ann created a recipe")
    assert created["who"] == "Ann" and created["detail"] == "Clean orders"
    assert created["href"] == f"/projects/{project}/pipelines/{recipe}"

    recipe_run = next(item for item in by_kind["runs"] if item["sentence"] == "Recipe run finished")
    assert recipe_run["who"] == "Ann" and recipe_run["detail"] == "Clean orders" and recipe_run["level"] == "success"

    [comment] = by_kind["comments"]
    assert comment["sentence"] == "Ann commented on the dataset Sample orders"
    assert comment["detail"] == "“These look doubled since Monday.”"
    assert comment["href"] == f"/projects/{project}/datasets/{dataset['id']}"

    [alert] = by_kind["alerts"]
    assert alert["sentence"] == "Sample orders: the row count is above 10" and alert["level"] == "warning"
    assert alert["href"] == f"/projects/{project}/datasets/{dataset['id']}/metrics"

    [incident] = by_kind["incidents"]
    assert incident["sentence"] == "An incident opened" and incident["detail"] == "Orders are late"
    assert incident["level"] == "error"


def test_the_stream_filters_and_pages_backwards(world) -> None:
    api, project = world["api"], world["project"]
    for name in ("One", "Two", "Three"):
        _ok(api.post(f"/api/v1/projects/{project}/dashboards", json={"name": name, "tiles": []}), 201)
    api.delete(f"/api/v1/projects/{project}/dashboards/{uuid.uuid4()}")  # refused: not found

    changes = _activity(world, kind="changes")["items"]
    assert all(item["kind"] == "changes" for item in changes)
    assert not any("deleted" in item["sentence"] for item in changes), "a refused attempt is not something that happened"
    made = {item["detail"] for item in changes if item["sentence"] == "Ann created a dashboard"}
    assert made == {"One", "Two", "Three"}, "what was made is named, not the project it was made in"

    first = _activity(world, kind="changes", limit=2)
    assert len(first["items"]) == 2 and first["next_offset"] == 2
    rest = _activity(world, kind="changes", limit=2, offset=first["next_offset"])
    seen = [item["id"] for item in first["items"] + rest["items"]]
    assert len(seen) == len(set(seen)) == 3, "every item once across pages"
    assert rest["next_offset"] is None, "three dashboards made: nothing more"

    assert _activity(world, kind=["runs", "alerts"])["items"] == []
    refused = api.get(f"/api/v1/projects/{project}/activity", params={"kind": "gossip"})
    assert refused.status_code == 400 and "no “gossip” activity" in refused.json()["detail"]


def test_a_deletion_names_what_went_and_a_script_names_its_person(world) -> None:
    api, project = world["api"], world["project"]
    gone = _ok(api.post(f"/api/v1/projects/{project}/dashboards", json={"name": "Old sales", "tiles": []}), 201)["id"]
    assert api.delete(f"/api/v1/projects/{project}/dashboards/{gone}").status_code == 204

    token = _ok(api.post("/api/v1/auth/tokens", json={"name": "Nightly script", "scope": "write"}), 201)["secret"]
    script = TestClient(app)
    script.headers["Authorization"] = f"Bearer {token}"
    _ok(script.post(f"/api/v1/projects/{project}/dashboards", json={"name": "From a script", "tiles": []}), 201)

    changes = _activity(world, kind="changes")["items"]
    deleted = next(item for item in changes if item["sentence"] == "Ann deleted a dashboard")
    assert deleted["detail"] == "Old sales", "named as it was before it went"
    scripted = next(item for item in changes if item["detail"] == "From a script")
    assert scripted["sentence"] == "Ann created a dashboard", "an API token's changes are its person's, not Someone's"
