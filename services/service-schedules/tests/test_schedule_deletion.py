"""Removing a schedule for good, rather than only switching it off.

`toggle` could disable a schedule, and that was the only way to retire one --
so a project accumulated every nightly job anyone had ever tried, all sitting
disabled in the list for ever.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.models import Project
from service_schedules.models import ScheduledOperation
from service_schedules.service import delete_schedule
from shared_python.db import Base
from shared_python.errors import NotFoundError


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
    stranger = User(username="stranger", password_hash="x", role="admin", is_active=True)
    db.add_all([owner, stranger])
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    schedule = ScheduledOperation(
        project_id=project.id,
        name="Nightly refresh",
        schedule_type="pipeline_run",
        cron_expression="0 2 * * *",
        enabled=True,
        target_config_json={"pipeline_id": str(uuid.uuid4())},
        created_by_user_id=owner.id,
    )
    db.add(schedule)
    db.commit()
    return {"owner": owner, "stranger": stranger, "project": project, "schedule": schedule}


def test_a_schedule_can_be_deleted(db: Session, world: dict):
    delete_schedule(
        db,
        project_id=world["project"].id,
        schedule_id=world["schedule"].id,
        current_user=_read(world["owner"]),
    )
    assert db.get(ScheduledOperation, world["schedule"].id) is None


def test_a_deleted_schedule_leaves_the_project_list(db: Session, world: dict):
    project_id = world["project"].id
    delete_schedule(
        db,
        project_id=project_id,
        schedule_id=world["schedule"].id,
        current_user=_read(world["owner"]),
    )
    remaining = db.scalars(
        select(ScheduledOperation).where(ScheduledOperation.project_id == project_id)
    ).all()
    assert remaining == []


def test_a_stranger_cannot_delete_a_schedule(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_schedule(
            db,
            project_id=world["project"].id,
            schedule_id=world["schedule"].id,
            current_user=_read(world["stranger"]),
        )
    assert db.get(ScheduledOperation, world["schedule"].id) is not None


def test_a_schedule_from_another_project_is_not_reachable(db: Session, world: dict):
    other = Project(name="Other", slug="other", owner_user_id=world["owner"].id, status="active")
    db.add(other)
    db.commit()

    with pytest.raises(NotFoundError):
        delete_schedule(
            db,
            project_id=other.id,
            schedule_id=world["schedule"].id,
            current_user=_read(world["owner"]),
        )
    assert db.get(ScheduledOperation, world["schedule"].id) is not None


def test_deleting_a_schedule_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_schedule(
            db,
            project_id=world["project"].id,
            schedule_id=uuid.uuid4(),
            current_user=_read(world["owner"]),
        )
