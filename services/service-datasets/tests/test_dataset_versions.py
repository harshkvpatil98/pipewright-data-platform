"""Immutable version history recorded on every materialisation (Phase 18).

These exercise the publication seam directly: `apply_*` advances the head and
appends a version but leaves the commit to its caller, while `finalize_*` owns
the commit. The two must never disagree about the current data, so the tests
assert head and version land -- or roll back -- together.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import uuid
from datetime import UTC, datetime

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_datasets.service import (
    apply_dataset_materialization_success,
    delete_dataset,
    finalize_dataset_materialization_success,
    get_dataset_version,
    get_dataset_version_preview,
    list_dataset_versions,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import NotFoundError
from shared_python.storage import content_digest


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


@pytest.fixture()
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    dataset = Dataset(project_id=project.id, name="sales", status="registered")
    db.add(dataset)
    db.commit()
    return {"owner": owner, "project": project, "dataset": dataset}


def _materialise(db: Session, dataset: Dataset, *, path: str, data: bytes, owner_id, **over):
    kwargs = dict(
        file_path=path,
        file_name=path.rsplit("/", 1)[-1],
        schema_json={"columns": [{"name": "amount", "inferred_type": "int"}]},
        schema_snapshot={"columns": [{"name": "amount", "inferred_type": "int"}]},
        preview_json={"rows": []},
        profile_json={"row_count": 3, "column_count": 1},
        row_count=3,
        column_count=1,
        content_hash=content_digest(data),
        created_by_user_id=owner_id,
    )
    kwargs.update(over)
    return finalize_dataset_materialization_success(db, dataset=dataset, **kwargs)


def _as_read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


def _versions(db: Session, dataset_id) -> list[DatasetVersion]:
    return list(
        db.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number)
        ).all()
    )


def test_a_materialisation_records_version_one(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/a.csv", data=b"amount\n1\n", owner_id=world["owner"].id)

    versions = _versions(db, dataset.id)
    assert [v.version_number for v in versions] == [1]
    version = versions[0]
    assert version.file_path == "uploads/a.csv"
    assert version.row_count == 3
    assert version.content_hash == content_digest(b"amount\n1\n")
    assert version.created_by_user_id == world["owner"].id
    # The head moved to ready alongside the version.
    assert dataset.status == "ready"
    assert dataset.ingestion_status == "succeeded"


def test_re_materialising_appends_a_monotonic_version(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/v2.csv", data=b"two", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/v3.csv", data=b"three", owner_id=world["owner"].id)

    versions = _versions(db, dataset.id)
    assert [v.version_number for v in versions] == [1, 2, 3]
    # History is not rewritten: the first version still points at its own bytes.
    assert versions[0].file_path == "uploads/v1.csv"
    assert versions[0].content_hash == content_digest(b"one")
    # The head reflects the latest publication.
    assert dataset.file_path == "uploads/v3.csv"


def test_identical_data_still_appends_a_version_with_the_same_digest(db: Session, world: dict):
    # Republishing the same bytes is a real event (a re-run); it gets its own
    # version, and the shared digest is what a later increment dedupes on.
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/a.csv", data=b"same", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/b.csv", data=b"same", owner_id=world["owner"].id)

    versions = _versions(db, dataset.id)
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].content_hash == versions[1].content_hash


def test_apply_flushes_but_leaves_the_commit_to_the_caller(db: Session, world: dict):
    # The transaction-ownership seam (§5): apply_ makes the head advance and the
    # version visible within the transaction, but a rollback undoes BOTH -- they
    # can never end up disagreeing about the current data.
    dataset = world["dataset"]
    apply_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path="uploads/x.csv",
        file_name="x.csv",
        schema_json={"columns": []},
        schema_snapshot={"columns": []},
        preview_json={"rows": []},
        profile_json={"row_count": 0, "column_count": 0},
        row_count=0,
        column_count=0,
        content_hash=content_digest(b"x"),
    )
    # Visible before commit within this session...
    assert len(_versions(db, dataset.id)) == 1
    assert dataset.status == "ready"

    db.rollback()

    # ...and gone together after a rollback.
    assert _versions(db, dataset.id) == []
    db.refresh(dataset)
    assert dataset.status == "registered"
    assert dataset.file_path is None


def test_a_version_number_cannot_be_duplicated(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/a.csv", data=b"one", owner_id=world["owner"].id)
    # A second version 1 for the same dataset is refused by the database, not by
    # a hopeful application check.
    db.add(
        DatasetVersion(
            dataset_id=dataset.id, version_number=1, file_path="uploads/dup.csv"
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_listing_versions_reads_newest_first_with_the_head(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/v2.csv", data=b"two", owner_id=world["owner"].id)

    listed = list_dataset_versions(db, world["project"].id, dataset.id, _as_read(world["owner"]))
    assert [v.version_number for v in listed.items] == [2, 1]
    assert listed.current_version == 2


def test_listing_a_dataset_with_no_history_is_empty_not_an_error(db: Session, world: dict):
    listed = list_dataset_versions(
        db, world["project"].id, world["dataset"].id, _as_read(world["owner"])
    )
    assert listed.items == []
    assert listed.current_version is None


def test_the_version_api_never_leaks_the_storage_key(db: Session, world: dict):
    # §4/§5: storage keys stay out of every API. A caller sees what changed and
    # when, not where the bytes live.
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/secret-key.csv", data=b"one", owner_id=world["owner"].id)
    listed = list_dataset_versions(db, world["project"].id, dataset.id, _as_read(world["owner"]))
    dumped = listed.model_dump()
    assert "file_path" not in dumped["items"][0]


def test_listing_versions_of_an_unknown_dataset_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        list_dataset_versions(
            db, world["project"].id, uuid.uuid4(), _as_read(world["owner"])
        )


def test_reading_a_version_as_of_returns_its_own_preview(db: Session, world: dict):
    # Time travel: each version keeps the preview it published, so an AS-OF read
    # shows the data as it was then, not the current head.
    dataset = world["dataset"]
    _materialise(
        db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id,
        preview_json={"columns": ["amount"], "rows": [{"amount": 1}]},
    )
    _materialise(
        db, dataset, path="uploads/v2.csv", data=b"two", owner_id=world["owner"].id,
        preview_json={"columns": ["amount"], "rows": [{"amount": 2}]},
    )

    read = get_dataset_version_preview(
        db, world["project"].id, dataset.id, 1, _as_read(world["owner"])
    )
    assert read.rows == [{"amount": 1}]
    head = get_dataset_version_preview(
        db, world["project"].id, dataset.id, 2, _as_read(world["owner"])
    )
    assert head.rows == [{"amount": 2}]


def test_reading_one_version_metadata(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    version = get_dataset_version(db, world["project"].id, dataset.id, 1, _as_read(world["owner"]))
    assert version.version_number == 1
    assert version.content_hash == content_digest(b"one")


def test_reading_a_version_that_does_not_exist_is_a_404(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    with pytest.raises(NotFoundError):
        get_dataset_version_preview(db, world["project"].id, dataset.id, 99, _as_read(world["owner"]))
    with pytest.raises(NotFoundError):
        get_dataset_version(db, world["project"].id, dataset.id, 99, _as_read(world["owner"]))


class _TrackingStorage:
    """Remembers deletions, so a test can assert which artifacts were reclaimed."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, path: str) -> None:
        self.deleted.append(path)


def test_deleting_a_dataset_reclaims_every_version_artifact(db: Session, world: dict):
    # Without this, the head file is reclaimed but every older snapshot leaks
    # on disk forever -- rows cascade away, bytes stay.
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/v2.csv", data=b"two", owner_id=world["owner"].id)

    storage = _TrackingStorage()
    delete_dataset(
        db, world["project"].id, dataset.id, _as_read(world["owner"]),
        storage_backend=storage,
    )
    assert sorted(storage.deleted) == ["uploads/v1.csv", "uploads/v2.csv"]


def test_a_version_artifact_shared_with_another_dataset_is_kept(db: Session, world: dict):
    dataset = world["dataset"]
    _materialise(db, dataset, path="uploads/v1.csv", data=b"one", owner_id=world["owner"].id)
    _materialise(db, dataset, path="uploads/v2.csv", data=b"two", owner_id=world["owner"].id)
    # A second dataset's head points at the first dataset's old snapshot.
    other = Dataset(
        project_id=world["project"].id, name="copy", status="ready",
        file_path="uploads/v1.csv",
    )
    db.add(other)
    db.commit()

    storage = _TrackingStorage()
    delete_dataset(
        db, world["project"].id, dataset.id, _as_read(world["owner"]),
        storage_backend=storage,
    )
    # v1 is still referenced by the other dataset; only v2 is reclaimed.
    assert storage.deleted == ["uploads/v2.csv"]


def test_a_version_without_the_bytes_records_a_null_digest(db: Session, world: dict):
    # content_hash is optional: a caller without the bytes in hand records the
    # version rather than fabricating a digest.
    dataset = world["dataset"]
    finalize_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path="uploads/a.csv",
        file_name="a.csv",
        schema_json={"columns": []},
        schema_snapshot={"columns": []},
        preview_json={"rows": []},
        profile_json={"row_count": 1, "column_count": 1},
        row_count=1,
        column_count=1,
    )
    assert _versions(db, dataset.id)[0].content_hash is None
