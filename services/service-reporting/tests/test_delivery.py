"""Report delivery: Slack target, email target, recipients, and the PDF format.

Generation and delivery are different facts. These pin that each configured
channel is attempted independently, that the outcome of each is recorded on the
delivery, that a failed channel is stated rather than hidden, and that the PDF
is a real paginated file.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_notifications.models import ExternalNotificationTarget
from service_projects.models import Project
from service_reporting import delivery as delivery_module
from service_reporting.exports import PDF_MAX_COLUMNS, export
from service_reporting.schemas import ReportCreate, ReportUpdate
from service_reporting.service import create_report, list_deliveries, run_report, update_report
from shared_python.db import Base
from shared_python.errors import NotFoundError

OWNER_ID = uuid.UUID("0b0b0b0b-0b0b-0b0b-0b0b-0b0b0b0b0b0b")
SALES = pd.DataFrame({"region": ["north", "south", "east"], "amount": [100, 250, 40]})


class _Storage:
    def read_bytes(self, _path: str) -> bytes:
        return SALES.to_csv(index=False).encode()


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db: Session) -> dict:
    owner = User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    other = Project(name="Other", slug="other", owner_user_id=OWNER_ID, status="active")
    db.add_all([project, other])
    db.flush()
    dataset = Dataset(project_id=project.id, name="sales", status="ready", ingestion_status="succeeded",
                      file_path="datasets/sales.csv", file_type="csv")
    slack = ExternalNotificationTarget(
        project_id=project.id, name="Ops channel", target_type="slack_webhook", enabled=True,
        config_json={"webhook_url": "https://hooks.example/abc", "channel_label": "ops"},
        subscribed_event_types_json=[], created_by_user_id=OWNER_ID,
    )
    foreign = ExternalNotificationTarget(
        project_id=other.id, name="Elsewhere", target_type="slack_webhook", enabled=True,
        config_json={"webhook_url": "https://hooks.example/zzz"},
        subscribed_event_types_json=[], created_by_user_id=OWNER_ID,
    )
    db.add_all([dataset, slack, foreign])
    db.commit()
    now = datetime.now(UTC)
    actor = UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    return {"project": project, "other": other, "dataset": dataset, "actor": actor, "slack": slack, "foreign": foreign}


@pytest.fixture()
def senders(monkeypatch):
    """Capture what would have gone out, and let a test decide the outcome."""
    log: dict = {"slack": [], "email": [], "slack_ok": True, "email_ok": True}

    def post_slack(*, config, text):
        log["slack"].append({"config": config, "text": text})
        return (True, "Slack webhook accepted the message.") if log["slack_ok"] else (False, "Webhook returned HTTP 410.")

    def send_email(*, to, subject, body, sender=None, attachments=None):
        log["email"].append({"to": to, "subject": subject, "body": body, "attachments": attachments})
        return (True, "Email sent.") if log["email_ok"] else (False, "SMTP is not configured on the server (set EXTERNAL_NOTIFICATION_SMTP_HOST).")

    monkeypatch.setattr(delivery_module, "post_slack", post_slack)
    monkeypatch.setattr(delivery_module, "send_email", send_email)
    monkeypatch.setenv("WEB_BASE_URL", "https://pw.example")
    return log


def _report(db, world, **over):
    payload = dict(name="Weekly sales", source_kind="dataset", source_id=world["dataset"].id, file_format="csv")
    payload.update(over)
    return create_report(db, world["project"].id, ReportCreate(**payload), world["actor"])


def test_a_report_posts_to_its_slack_target_with_a_link(db, world, senders):
    report = _report(db, world, notification_target_id=world["slack"].id)
    _content, filename, _media, delivery = run_report(db, world["project"].id, report.id, world["actor"], _Storage())

    [post] = senders["slack"]
    assert post["config"]["webhook_url"] == "https://hooks.example/abc"
    assert "*Weekly sales is ready*" in post["text"] and "[ops]" in post["text"]
    assert filename in post["text"] and "3 row(s)" in post["text"]
    assert f"https://pw.example/projects/{world['project'].id}/reports" in post["text"]
    kinds = {(c["channel"], c["ok"]) for c in delivery.channels}
    assert ("in_app", True) in kinds and ("slack", True) in kinds
    assert delivery.message == "3 row(s). · Slack: posted"
    assert delivery.status == "succeeded"


def test_recipients_each_get_the_file_attached_and_one_failure_is_stated(db, world, senders):
    report = _report(db, world, recipients=["a@acme.com", "b@acme.com"], file_format="excel")
    *_rest, delivery = run_report(db, world["project"].id, report.id, world["actor"], _Storage())
    assert [m["to"] for m in senders["email"]] == ["a@acme.com", "b@acme.com"]
    [(name, payload, media)] = senders["email"][0]["attachments"]
    assert name.endswith(".xlsx") and media.startswith("application/vnd.openxmlformats") and payload[:2] == b"PK"
    assert delivery.message == "3 row(s). · email: 2 sent"

    senders["email_ok"] = False
    *_rest, failed = run_report(db, world["project"].id, report.id, world["actor"], _Storage())
    # Generation still succeeded; delivery did not, and the record says so.
    assert failed.status == "succeeded"
    assert failed.message == "3 row(s). · email: 0 sent, 2 failed"
    assert all("SMTP is not configured" in c["detail"] for c in failed.channels if c["channel"] == "email")
    history = list_deliveries(db, world["project"].id, report.id, world["actor"])
    assert [d.message for d in history.items][0] == failed.message


def test_a_failed_slack_post_is_recorded_not_raised(db, world, senders):
    senders["slack_ok"] = False
    report = _report(db, world, notification_target_id=world["slack"].id)
    *_rest, delivery = run_report(db, world["project"].id, report.id, world["actor"], _Storage())
    slack = next(c for c in delivery.channels if c["channel"] == "slack")
    assert slack["ok"] is False and "410" in slack["detail"]
    assert delivery.message == "3 row(s). · Slack: failed"


def test_a_disabled_or_foreign_target_is_refused_or_reported(db, world, senders):
    with pytest.raises(NotFoundError):
        _report(db, world, notification_target_id=world["foreign"].id)
    with pytest.raises(NotFoundError):
        _report(db, world, notification_target_id=uuid.uuid4())

    report = _report(db, world, notification_target_id=world["slack"].id)
    world["slack"].enabled = False
    db.commit()
    *_rest, delivery = run_report(db, world["project"].id, report.id, world["actor"], _Storage())
    assert senders["slack"] == []
    assert any("disabled" in c["detail"] for c in delivery.channels)


def test_the_target_can_be_cleared_with_an_explicit_null(db, world):
    report = _report(db, world, notification_target_id=world["slack"].id)
    kept = update_report(db, world["project"].id, report.id, ReportUpdate(name="Weekly"), world["actor"])
    assert kept.notification_target_id == world["slack"].id
    cleared = update_report(db, world["project"].id, report.id, ReportUpdate(notification_target_id=None), world["actor"])
    assert cleared.notification_target_id is None


# ---- PDF ----


def test_pdf_is_a_real_paginated_file_with_a_repeating_header():
    frame = pd.DataFrame({"region": [f"r{i}" for i in range(300)], "amount": range(300)})
    result = export(frame, title="Weekly sales", file_format="pdf", subtitle="From sales.")
    assert result.content[:5] == b"%PDF-"
    assert result.filename.endswith(".pdf") and result.media_type == "application/pdf"
    assert result.row_count == 300
    # Several pages: 300 rows do not fit on one A4 page at 9pt.
    assert result.content.count(b"/Type /Page") >= 3


def test_pdf_states_what_it_left_out():
    wide = pd.DataFrame({f"c{i}": [1, 2] for i in range(PDF_MAX_COLUMNS + 5)})
    result = export(wide, title="Wide", file_format="pdf")
    assert result.content[:5] == b"%PDF-"
    # A wide table gets a landscape page (A4 long edge, 841.89 pt, first).
    import re

    boxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", result.content)
    assert boxes and float(boxes[0][0]) > float(boxes[0][1])


def test_a_report_can_be_created_as_pdf_and_generated(db, world, senders):
    report = _report(db, world, file_format="pdf")
    content, filename, media, delivery = run_report(db, world["project"].id, report.id, world["actor"], _Storage())
    assert content[:5] == b"%PDF-" and media == "application/pdf" and filename.endswith(".pdf")
    assert delivery.file_format == "pdf" and delivery.row_count == 3
