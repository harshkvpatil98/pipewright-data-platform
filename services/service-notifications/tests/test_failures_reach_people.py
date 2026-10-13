"""Failures reach the people who can act on them (adoption-readiness A6, W6).

An incident tells the owner and every member who can act on it, in the app,
and the project's subscribed email and Slack targets, once. A weekly summary
goes to the targets that ask for it, once a week. Messages read in words.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
from service_access.models import ProjectMembership
from service_auth.models import User
from service_notifications.constants import ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES
from service_notifications.models import ExternalNotificationTarget, UserNotification
from service_notifications.preferences import set_mode
from service_notifications.service import create_user_notification
from service_projects.models import Project
from shared_python.db import Base


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
    people = {name: User(username=name, password_hash="x", role="user", is_active=True) for name in ("owner", "op", "viewer")}
    db.add_all(people.values())
    db.flush()
    project = Project(name="Shop", slug="shop", status="active", owner_user_id=people["owner"].id)
    db.add(project)
    db.flush()
    db.add_all([
        ProjectMembership(project_id=project.id, user_id=people["op"].id, role="operator"),
        ProjectMembership(project_id=project.id, user_id=people["viewer"].id, role="viewer"),
    ])
    target = ExternalNotificationTarget(
        project_id=project.id, name="Ops mailbox", target_type="email", enabled=True,
        config_json={"recipient_email": "ops@example.com", "sender_email": "", "subject_prefix": "[Shop]"},
        subscribed_event_types_json=["incident_opened", "weekly_summary"], created_by_user_id=people["owner"].id,
    )
    db.add(target)
    db.commit()
    return {"project": project, "people": people, "target": target}


def _sent(monkeypatch, module: str) -> list[dict]:
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return True, "sent"

    monkeypatch.setattr(f"{module}.send_email_event_message", fake)
    return calls


def test_the_new_events_can_be_subscribed_to() -> None:
    assert {"incident_opened", "workflow_run_failed", "workflow_run_partial", "weekly_summary"} <= ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES


def test_an_incident_reaches_everyone_who_can_act_and_the_mailbox_once(db: Session, world: dict, monkeypatch) -> None:
    from service_observability.incidents import report

    sent = _sent(monkeypatch, "service_notifications.external_dispatch")
    for _ in range(2):  # the second occurrence of the same incident tells nobody again
        report(db, project_id=world["project"].id, fingerprint="check:orders", title="Orders failed a check",
               summary="3 rows have no email.", source_kind="quality", severity="high")
        db.commit()
    told = {row.user_id for row in db.scalars(select(UserNotification).where(UserNotification.type == "incident"))}
    assert told == {world["people"]["owner"].id, world["people"]["op"].id}
    assert len(sent) == 1
    assert sent[0]["title"] == "Incident: Orders failed a check"
    assert sent[0]["event_type"] == "incident_opened"


def test_the_weekly_summary_goes_once_a_week(db: Session, world: dict, monkeypatch) -> None:
    from service_notifications.weekly import send_weekly_summaries

    sent = _sent(monkeypatch, "service_notifications.weekly")
    now = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    assert send_weekly_summaries(db, now=now) == 1
    assert send_weekly_summaries(db, now=now + timedelta(days=3)) == 0
    assert send_weekly_summaries(db, now=now + timedelta(days=7)) == 1
    assert len(sent) == 2
    assert sent[0]["title"] == "Shop: the week in brief"
    assert "No runs this week." in sent[0]["message"]


def test_a_weekly_preference_folds_events_into_one_row_for_the_week(db: Session, world: dict) -> None:
    owner = world["people"]["owner"]
    set_mode(db, owner.id, "successes", "weekly")
    for _ in range(3):
        create_user_notification(db, user_id=owner.id, project_id=None, type="schedule_run_succeeded",
                                 level="success", title="Refresh finished", message="All good.")
    rows = list(db.scalars(select(UserNotification).where(UserNotification.user_id == owner.id)))
    assert len(rows) == 1
    assert rows[0].title == "3 runs finished without problems this week"


def test_emails_and_slack_messages_are_in_words() -> None:
    from service_notifications.senders.slack_sender import _payload_text

    text = _payload_text(title="Incident: Orders failed a check", message="3 rows.", level="error", event_type="incident_opened")
    assert "An incident opened · Needs attention" in text
    assert "incident_opened" not in text
