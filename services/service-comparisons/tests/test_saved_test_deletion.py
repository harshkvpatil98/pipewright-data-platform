"""Deleting a saved statistical test, and the runs recorded against it.

A saved test could be created and re-run and never removed. The runs go with
it: `saved_statistical_test_runs.saved_test_id` is `ON DELETE CASCADE`, so
there is no separate sweep to forget and no way to leave a run pointing at a
test that no longer exists.

Foreign keys are switched on for these, because SQLite ignores
`ON DELETE CASCADE` without the pragma -- which would make the one assertion
that matters here pass for the wrong reason.
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
from service_comparisons.models import SavedStatisticalTest, SavedStatisticalTestRun
from service_comparisons.saved_tests_service import delete_saved_statistical_test
from service_datasets.models import Dataset
from service_projects.models import Project
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
    left = Dataset(project_id=project.id, name="january")
    right = Dataset(project_id=project.id, name="february")
    db.add_all([left, right])
    db.flush()
    saved = SavedStatisticalTest(
        project_id=project.id,
        name="Revenue drift",
        test_type="t_test",
        column_name="revenue",
        left_dataset_id=left.id,
        right_dataset_id=right.id,
        created_by_user_id=owner.id,
    )
    db.add(saved)
    db.flush()
    db.add(
        SavedStatisticalTestRun(
            saved_test_id=saved.id,
            project_id=project.id,
            status="succeeded",
            result_json={"p_value": 0.03},
        )
    )
    db.commit()
    return {"owner": owner, "stranger": stranger, "project": project, "saved": saved}


def test_a_saved_test_can_be_deleted(db: Session, world: dict):
    delete_saved_statistical_test(
        db, world["project"].id, world["saved"].id, _read(world["owner"])
    )
    assert db.get(SavedStatisticalTest, world["saved"].id) is None


def test_deleting_a_saved_test_takes_its_runs_with_it(db: Session, world: dict):
    saved_id = world["saved"].id
    assert db.scalars(
        select(SavedStatisticalTestRun).where(SavedStatisticalTestRun.saved_test_id == saved_id)
    ).all()

    delete_saved_statistical_test(db, world["project"].id, saved_id, _read(world["owner"]))

    assert (
        db.scalars(
            select(SavedStatisticalTestRun).where(
                SavedStatisticalTestRun.saved_test_id == saved_id
            )
        ).all()
        == []
    )


def test_a_stranger_cannot_delete_a_saved_test(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_saved_statistical_test(
            db, world["project"].id, world["saved"].id, _read(world["stranger"])
        )
    assert db.get(SavedStatisticalTest, world["saved"].id) is not None


def test_a_saved_test_from_another_project_is_not_reachable(db: Session, world: dict):
    other = Project(name="Other", slug="other", owner_user_id=world["owner"].id, status="active")
    db.add(other)
    db.commit()

    with pytest.raises(NotFoundError):
        delete_saved_statistical_test(
            db, other.id, world["saved"].id, _read(world["owner"])
        )
    assert db.get(SavedStatisticalTest, world["saved"].id) is not None


def test_deleting_a_saved_test_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_saved_statistical_test(
            db, world["project"].id, uuid.uuid4(), _read(world["owner"])
        )
