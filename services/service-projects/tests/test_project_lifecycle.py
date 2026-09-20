"""Renaming, archiving and deleting a project, over real rows.

A project used to be write-once. It could be created and then never renamed,
never described, never archived and never removed -- so a typo in a name was
permanent, and a workspace made by accident stayed in the list for ever. The
instance these tests were written against had forty-five projects, forty of
them left behind by end-to-end runs, holding forty-six datasets between them.

The delete tests run with SQLite's foreign keys switched on. That is not
decoration: SQLite ignores `ON DELETE CASCADE` unless `PRAGMA foreign_keys` is
set, so without it `delete_project` would appear to pass here while leaving
every dataset orphaned, and the one thing these tests exist to prove -- that
the contents go too -- would be untested.
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
from service_datasets.models import Dataset
from service_projects.models import Project
from service_projects.schemas import ProjectUpdate
from service_projects.service import delete_project, list_projects, update_project
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


def _user(db: Session, username: str) -> User:
    row = User(username=username, password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    return row


def _read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    owner = _user(db, "owner")
    stranger = _user(db, "stranger")
    project = Project(
        name="Reveune Quality",  # the typo is the point
        slug="revenue-quality",
        owner_user_id=owner.id,
        status="active",
        description="Finance workspace",
    )
    db.add(project)
    db.flush()
    dataset = Dataset(project_id=project.id, name="orders")
    db.add(dataset)
    db.commit()
    return {"owner": owner, "stranger": stranger, "project": project, "dataset": dataset}


# ----------------------------------------------------------------- renaming


def test_a_project_can_be_renamed(db: Session, world: dict):
    updated = update_project(
        db, world["project"].id, ProjectUpdate(name="Revenue Quality"), _read(world["owner"])
    )
    assert updated.name == "Revenue Quality"


def test_renaming_does_not_blank_the_description(db: Session, world: dict):
    """The reason `exclude_unset` is load-bearing.

    Reading the fields off the model directly turns every omitted field into an
    explicit null, so a rename would quietly erase the description.
    """
    updated = update_project(
        db, world["project"].id, ProjectUpdate(name="Revenue Quality"), _read(world["owner"])
    )
    assert updated.description == "Finance workspace"


def test_a_description_can_be_added_to_a_project_that_has_none(db: Session, world: dict):
    """The project card says "add one"; until now nothing could."""
    project = Project(name="Bare", slug="bare", owner_user_id=world["owner"].id, status="active")
    db.add(project)
    db.commit()

    updated = update_project(
        db, project.id, ProjectUpdate(description="What this is for"), _read(world["owner"])
    )
    assert updated.description == "What this is for"


def test_a_description_can_be_cleared_explicitly(db: Session, world: dict):
    """Distinct from omitting it, and the only way back from a mistake."""
    updated = update_project(
        db, world["project"].id, ProjectUpdate(description=None), _read(world["owner"])
    )
    assert updated.description is None


def test_a_project_can_be_archived(db: Session, world: dict):
    """`archived` was already a legal status with no way to reach it."""
    updated = update_project(
        db, world["project"].id, ProjectUpdate(status="archived"), _read(world["owner"])
    )
    assert updated.status == "archived"


def test_renaming_leaves_the_slug_alone(db: Session, world: dict):
    """The slug is what links point at, so it does not follow the display name."""
    updated = update_project(
        db, world["project"].id, ProjectUpdate(name="Something Else"), _read(world["owner"])
    )
    assert updated.slug == "revenue-quality"


def test_a_stranger_cannot_rename_a_project(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        update_project(
            db, world["project"].id, ProjectUpdate(name="Mine now"), _read(world["stranger"])
        )


# ------------------------------------------------------------------ deleting


def test_a_project_can_be_deleted(db: Session, world: dict):
    delete_project(db, world["project"].id, _read(world["owner"]))
    assert db.get(Project, world["project"].id) is None


def test_deleting_a_project_takes_its_datasets_with_it(db: Session, world: dict):
    """What made this worth doing carefully.

    Forty-six datasets sat inside projects that could not be removed. Deleting
    the project has to remove them too -- an orphaned dataset row pointing at a
    project that no longer exists is worse than either outcome.
    """
    dataset_id = world["dataset"].id
    assert db.get(Dataset, dataset_id) is not None

    delete_project(db, world["project"].id, _read(world["owner"]))

    assert db.scalar(select(Dataset).where(Dataset.id == dataset_id)) is None


def test_a_deleted_project_leaves_the_list(db: Session, world: dict):
    owner = _read(world["owner"])
    assert len(list_projects(db, owner).items) == 1
    delete_project(db, world["project"].id, owner)
    assert list_projects(db, owner).items == []


def test_a_stranger_cannot_delete_a_project(db: Session, world: dict):
    """And is told it does not exist, rather than that they may not touch it."""
    with pytest.raises(NotFoundError):
        delete_project(db, world["project"].id, _read(world["stranger"]))
    assert db.get(Project, world["project"].id) is not None


def test_deleting_a_project_that_is_already_gone_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_project(db, uuid.uuid4(), _read(world["owner"]))
