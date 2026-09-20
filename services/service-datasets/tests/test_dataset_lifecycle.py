"""Renaming and deleting a dataset, including what happens to its bytes.

A dataset took its name from the uploaded file and kept it for ever, and there
was no way to remove one at all -- so a mistaken import stayed in the project,
in every picker, for the life of the workspace.

Deleting one has to reach outside the database. The row points at a stored
artifact, and the interesting cases are the ones where that file is shared with
another dataset, or where removing it fails.
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
from service_datasets.schemas import DatasetUpdate
from service_datasets.service import delete_dataset, update_dataset
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import NotFoundError


class RecordingStorage:
    """A storage backend that remembers what it was asked to remove."""

    def __init__(self, *, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self.fail = fail

    def delete(self, relative_path: str) -> None:
        if self.fail:
            raise OSError("storage is unreachable")
        self.deleted.append(relative_path)


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
    dataset = Dataset(
        project_id=project.id,
        name="export_final_v2 (3).csv",
        file_path="uploads/ops/export.csv",
    )
    db.add(dataset)
    db.commit()
    return {"owner": owner, "stranger": stranger, "project": project, "dataset": dataset}


def test_a_dataset_can_be_renamed(db: Session, world: dict):
    updated = update_dataset(
        db, world["project"].id, world["dataset"].id,
        DatasetUpdate(name="Orders"), _read(world["owner"]),
    )
    assert updated.name == "Orders"


def test_renaming_leaves_the_original_filename_alone(db: Session, world: dict):
    """The display name is a label; the filename is a fact about what was read."""
    update_dataset(
        db, world["project"].id, world["dataset"].id,
        DatasetUpdate(name="Orders"), _read(world["owner"]),
    )
    assert db.get(Dataset, world["dataset"].id).file_path == "uploads/ops/export.csv"


def test_a_stranger_cannot_rename_a_dataset(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        update_dataset(
            db, world["project"].id, world["dataset"].id,
            DatasetUpdate(name="Mine"), _read(world["stranger"]),
        )


def test_a_dataset_can_be_deleted(db: Session, world: dict):
    delete_dataset(db, world["project"].id, world["dataset"].id, _read(world["owner"]))
    assert db.get(Dataset, world["dataset"].id) is None


def test_deleting_a_dataset_removes_its_stored_file(db: Session, world: dict):
    storage = RecordingStorage()
    delete_dataset(
        db, world["project"].id, world["dataset"].id, _read(world["owner"]),
        storage_backend=storage,
    )
    assert storage.deleted == ["uploads/ops/export.csv"]


def test_a_file_shared_with_another_dataset_is_kept(db: Session, world: dict):
    """A derived dataset can be materialised from its parent's artifact.

    Deleting the copy must not take the original's bytes with it, which would
    leave a dataset that lists fine and fails the moment anyone opens it.
    """
    sibling = Dataset(
        project_id=world["project"].id,
        name="orders (copy)",
        file_path="uploads/ops/export.csv",
    )
    db.add(sibling)
    db.commit()

    storage = RecordingStorage()
    delete_dataset(
        db, world["project"].id, world["dataset"].id, _read(world["owner"]),
        storage_backend=storage,
    )

    assert storage.deleted == [], "the surviving dataset still points at that file"
    assert db.get(Dataset, sibling.id) is not None


def test_a_storage_failure_does_not_resurrect_the_dataset(db: Session, world: dict):
    """The row is already gone by then, so the caller's request did succeed.

    Raising here would report the whole deletion as failed and invite a retry
    that can only 404, while the dataset stays deleted either way.
    """
    delete_dataset(
        db, world["project"].id, world["dataset"].id, _read(world["owner"]),
        storage_backend=RecordingStorage(fail=True),
    )
    assert db.get(Dataset, world["dataset"].id) is None


def test_a_dataset_with_no_file_deletes_cleanly(db: Session, world: dict):
    """A registered-but-never-ingested dataset has nothing to clean up."""
    empty = Dataset(project_id=world["project"].id, name="never ingested")
    db.add(empty)
    db.commit()

    storage = RecordingStorage()
    delete_dataset(
        db, world["project"].id, empty.id, _read(world["owner"]), storage_backend=storage
    )
    assert db.get(Dataset, empty.id) is None
    assert storage.deleted == []


def test_a_stranger_cannot_delete_a_dataset(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_dataset(
            db, world["project"].id, world["dataset"].id, _read(world["stranger"])
        )
    assert db.get(Dataset, world["dataset"].id) is not None


def test_a_dataset_from_another_project_is_not_reachable(db: Session, world: dict):
    """The project in the path has to be the one the dataset is in."""
    other = Project(name="Other", slug="other", owner_user_id=world["owner"].id, status="active")
    db.add(other)
    db.commit()

    with pytest.raises(NotFoundError):
        delete_dataset(db, other.id, world["dataset"].id, _read(world["owner"]))
    assert db.get(Dataset, world["dataset"].id) is not None


def test_deleting_a_dataset_that_is_already_gone_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_dataset(db, world["project"].id, uuid.uuid4(), _read(world["owner"]))


def test_a_deleted_dataset_leaves_the_project_list(db: Session, world: dict):
    project_id = world["project"].id
    delete_dataset(db, project_id, world["dataset"].id, _read(world["owner"]))
    remaining = db.scalars(select(Dataset).where(Dataset.project_id == project_id)).all()
    assert remaining == []
