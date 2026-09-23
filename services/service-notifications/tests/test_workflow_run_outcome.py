"""Workflow (DAG) run outcomes now notify, like every other kind of run.

The multi-step run a worker executes with nobody watching was the one kind of
failure that used to say nothing. These pin that a failure and a partial finish
each land an in-app notification, and that a clean success stays quiet so the
bell does not become noise.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_notifications.models import UserNotification
from service_notifications.outcomes import notify_workflow_run_outcome
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
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.commit()
    return {"owner": owner, "project": project}


def _notifications(db: Session) -> list[UserNotification]:
    return list(db.scalars(select(UserNotification)))


def test_a_failed_workflow_run_notifies(db: Session, world: dict) -> None:
    notify_workflow_run_outcome(
        db,
        user_id=world["owner"].id,
        project_id=world["project"].id,
        workflow_name="Nightly refresh",
        status="failed",
        error="node 'load' raised",
    )
    rows = _notifications(db)
    assert len(rows) == 1
    assert rows[0].type == "workflow_run_failed"
    assert rows[0].level == "error"
    assert "Nightly refresh" in rows[0].message


def test_a_partial_workflow_run_warns(db: Session, world: dict) -> None:
    notify_workflow_run_outcome(
        db,
        user_id=world["owner"].id,
        project_id=world["project"].id,
        workflow_name="Nightly refresh",
        status="partial",
    )
    rows = _notifications(db)
    assert len(rows) == 1
    assert rows[0].type == "workflow_run_partial"
    assert rows[0].level == "warning"


def test_a_successful_workflow_run_stays_quiet(db: Session, world: dict) -> None:
    notify_workflow_run_outcome(
        db,
        user_id=world["owner"].id,
        project_id=world["project"].id,
        workflow_name="Nightly refresh",
        status="succeeded",
    )
    assert _notifications(db) == []
