"""Deleting a notification target, and the report that stops it.

A target could be created and never removed, so a project collected every
webhook anyone had ever tried. Deleting one has to account for
`scheduled_reports.notification_target_id`, which is a plain column with no
foreign key behind it: nothing in the database would object to the target
disappearing, and the report would keep its schedule, keep running, and
deliver to nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_notifications.models import ExternalNotificationTarget
from service_notifications.targets_service import delete_target
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import ConflictError, NotFoundError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    target = ExternalNotificationTarget(
        project_id=project.id,
        name="Ops Slack",
        target_type="slack_webhook",
        enabled=True,
        config_json={"webhook_url": "https://hooks.slack.com/services/T/B/X"},
        subscribed_event_types_json=["schedule_run_failed"],
        created_by_user_id=owner.id,
    )
    db.add(target)
    db.commit()
    return {"owner": owner, "project": project, "target": target}


def _attach_report(db: Session, project_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """A scheduled report that delivers to this target.

    The model is imported here rather than in `targets_service`: a test may
    know about both services, while the production code must not -- which is
    exactly why the count inside `delete_target` is a text query.
    """
    from service_reporting.models import ScheduledReport

    db.add(
        ScheduledReport(
            project_id=project_id,
            name="Weekly",
            source_kind="dataset",
            source_id=uuid.uuid4(),
            file_format="pdf",
            cron_expression="0 9 * * 1",
            enabled=True,
            notification_target_id=target_id,
            run_count=0,
        )
    )
    db.commit()


def test_a_notification_target_can_be_deleted(db: Session, world: dict):
    delete_target(
        db,
        project_id=world["project"].id,
        target_id=world["target"].id,
        current_user=_read(world["owner"]),
    )
    assert db.get(ExternalNotificationTarget, world["target"].id) is None


def test_a_target_a_report_still_delivers_to_is_kept(db: Session, world: dict):
    """The refusal, and the reason it is not left to the database.

    There is no foreign key on `notification_target_id`, so deleting the target
    would succeed silently and leave the report delivering nowhere.
    """
    _attach_report(db, world["project"].id, world["target"].id)

    with pytest.raises(ConflictError, match="scheduled report"):
        delete_target(
            db,
            project_id=world["project"].id,
            target_id=world["target"].id,
            current_user=_read(world["owner"]),
        )

    assert db.get(ExternalNotificationTarget, world["target"].id) is not None


def test_the_refusal_says_how_many_reports_are_in_the_way(db: Session, world: dict):
    _attach_report(db, world["project"].id, world["target"].id)
    _attach_report(db, world["project"].id, world["target"].id)

    with pytest.raises(ConflictError, match="2 scheduled report"):
        delete_target(
            db,
            project_id=world["project"].id,
            target_id=world["target"].id,
            current_user=_read(world["owner"]),
        )


def test_a_report_on_a_different_target_does_not_block_this_one(db: Session, world: dict):
    """The count has to be scoped to the target being deleted, not the project."""
    other = ExternalNotificationTarget(
        project_id=world["project"].id,
        name="Other Slack",
        target_type="slack_webhook",
        enabled=True,
        config_json={"webhook_url": "https://hooks.slack.com/services/T/B/Y"},
        subscribed_event_types_json=["schedule_run_failed"],
        created_by_user_id=world["owner"].id,
    )
    db.add(other)
    db.commit()
    _attach_report(db, world["project"].id, other.id)

    delete_target(
        db,
        project_id=world["project"].id,
        target_id=world["target"].id,
        current_user=_read(world["owner"]),
    )
    assert db.get(ExternalNotificationTarget, world["target"].id) is None


def test_a_target_from_another_project_is_not_reachable(db: Session, world: dict):
    other_project = Project(
        name="Other", slug="other", owner_user_id=world["owner"].id, status="active",
    )
    db.add(other_project)
    db.commit()

    with pytest.raises(NotFoundError):
        delete_target(
            db,
            project_id=other_project.id,
            target_id=world["target"].id,
            current_user=_read(world["owner"]),
        )
    assert db.get(ExternalNotificationTarget, world["target"].id) is not None


def test_deleting_a_target_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_target(
            db,
            project_id=world["project"].id,
            target_id=uuid.uuid4(),
            current_user=_read(world["owner"]),
        )
