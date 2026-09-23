"""Erasure lifecycle: correction vs destructive, and never a silent success.

The failure this guards against is reporting "erased" while the bytes are still
readable. These pin: a correction clears the live base data and completes; a
destructive erasure refuses to overwrite a derived artifact in place and reports
it blocked; and any dataset that could not be read blocks completion rather than
being quietly skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_enterprise.schemas import ErasureCreate
from service_enterprise.service import request_erasure
from service_projects.models import Project
from shared_python.db import Base
from shared_python.storage import content_digest

NOW = datetime(2026, 9, 23, tzinfo=UTC)
CSV = b"name,email\nAlice,alice@acme.com\nBob,bob@acme.com\n"


class _Storage:
    """A mutable file store: erasure reads a file, redacts, and writes it back."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_bytes(self, path: str, payload: bytes) -> None:
        self.files[path] = payload


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


def _read(user: User) -> UserRead:
    return UserRead(id=user.id, username=user.username, role="admin", is_active=True,
                    created_at=NOW, updated_at=NOW)


def _dataset(db, project, storage, name, *, path, derived=False, seed=CSV) -> Dataset:
    ds = Dataset(
        project_id=project.id, name=name, status="ready", ingestion_status="succeeded",
        file_path=path, file_type="csv", is_derived=derived,
    )
    db.add(ds)
    db.flush()
    if seed is not None:
        storage.files[path] = seed
    return ds


@pytest.fixture()
def world(db: Session):
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    db.commit()
    return {"owner": owner, "project": project, "storage": _Storage()}


def test_report_only_finds_the_subject_without_touching_data(db: Session, world: dict) -> None:
    storage = world["storage"]
    _dataset(db, world["project"], storage, "customers", path="d/customers.csv")
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", subject_kind="email", apply=False),
        _read(world["owner"]), storage,
    )
    assert result.status == "reported"
    assert b"alice@acme.com" in storage.files["d/customers.csv"]  # untouched


def test_correction_appends_a_clean_head_and_keeps_history_readable(
    db: Session, world: dict
) -> None:
    """Correction is forward-moving: the head advances to a corrected version;
    the artifact that held the subject stays readable as history. That is the
    documented difference from a destructive erasure (phase-18 §2)."""
    storage = world["storage"]
    ds = _dataset(db, world["project"], storage, "customers", path="d/customers.csv")
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"
    assert result.report["erased"] == ["customers"]

    db.refresh(ds)
    # The head moved to a new, clean artifact...
    assert ds.file_path != "d/customers.csv"
    head_bytes = storage.files[ds.file_path]
    assert b"alice@acme.com" not in head_bytes
    assert b"bob@acme.com" in head_bytes  # others untouched
    # ...the head's own preview no longer carries the subject...
    assert "alice@acme.com" not in str(ds.preview_json)
    # ...and history remains readable: the original bytes are still there.
    assert b"alice@acme.com" in storage.files["d/customers.csv"]
    # The correction was published as a version whose hash tells the truth.
    versions = list(db.scalars(select(DatasetVersion).where(
        DatasetVersion.dataset_id == ds.id)).all())
    assert [v.version_number for v in versions] == [1]
    assert versions[0].content_hash == content_digest(head_bytes)


def test_destructive_refuses_to_overwrite_a_derived_artifact(db: Session, world: dict) -> None:
    storage = world["storage"]
    _dataset(db, world["project"], storage, "base", path="d/base.csv")
    _dataset(db, world["project"], storage, "derived", path="d/derived.csv", derived=True)
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="destructive"),
        _read(world["owner"]), storage,
    )
    # The base is cleared; the derived one is blocked, not corrupted or claimed.
    assert "base" in result.report["erased"]
    assert b"alice@acme.com" not in storage.files["d/base.csv"]
    assert b"alice@acme.com" in storage.files["d/derived.csv"]  # untouched
    blocked_names = [b["dataset"] for b in result.report["blocked"]]
    assert "derived" in blocked_names
    # Some erased, some blocked -> partial, never "completed".
    assert result.status == "partial"


def test_a_correction_over_a_derived_dataset_still_advances_its_head(
    db: Session, world: dict
) -> None:
    # Correction is not the strict historical claim, so a derived dataset's head
    # can be corrected too — it just advances, like any other correction.
    storage = world["storage"]
    ds = _dataset(db, world["project"], storage, "derived", path="d/derived.csv", derived=True)
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"
    db.refresh(ds)
    assert b"alice@acme.com" not in storage.files[ds.file_path]


def test_destructive_scrubs_every_historical_version(db: Session, world: dict) -> None:
    """The failure §2 names: a clean head whose old bytes are still readable
    through history. Destructive rewrites each version artifact, re-digests it
    so the recorded hash keeps telling the truth, and scrubs the previews."""
    storage = world["storage"]
    ds = _dataset(db, world["project"], storage, "customers", path="d/v2.csv")
    storage.files["d/v1.csv"] = CSV  # the older snapshot holds the subject too
    db.add_all([
        DatasetVersion(
            dataset_id=ds.id, version_number=1, file_path="d/v1.csv", file_type="csv",
            content_hash=content_digest(CSV),
            preview_json={"columns": ["email"], "rows": [{"email": "alice@acme.com"}]},
        ),
        DatasetVersion(
            dataset_id=ds.id, version_number=2, file_path="d/v2.csv", file_type="csv",
            content_hash=content_digest(CSV),
            preview_json={"columns": ["email"], "rows": [{"email": "alice@acme.com"}]},
        ),
    ])
    db.commit()

    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="destructive"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"

    # Both artifacts scrubbed — history included.
    assert b"alice@acme.com" not in storage.files["d/v1.csv"]
    assert b"alice@acme.com" not in storage.files["d/v2.csv"]
    versions = {
        v.version_number: v
        for v in db.scalars(select(DatasetVersion).where(
            DatasetVersion.dataset_id == ds.id)).all()
    }
    # Hashes re-recorded to match the new bytes: no version row lies.
    assert versions[1].content_hash == content_digest(storage.files["d/v1.csv"])
    assert versions[2].content_hash == content_digest(storage.files["d/v2.csv"])
    # Previews scrubbed too — they carried the subject as raw rows.
    assert "alice@acme.com" not in str(versions[1].preview_json)
    assert "alice@acme.com" not in str(versions[2].preview_json)
    db.refresh(ds)
    assert "alice@acme.com" not in str(ds.preview_json)


def test_destructive_reports_an_unreadable_version_as_blocked(
    db: Session, world: dict
) -> None:
    storage = world["storage"]
    ds = _dataset(db, world["project"], storage, "customers", path="d/head.csv")
    # A version whose artifact is gone from storage cannot be claimed clean.
    db.add(DatasetVersion(
        dataset_id=ds.id, version_number=1, file_path="d/lost.csv", file_type="csv",
    ))
    db.commit()

    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="destructive"),
        _read(world["owner"]), storage,
    )
    assert result.status == "partial"  # live data gone, history not provably clean
    blocked = [b["dataset"] for b in result.report["blocked"]]
    assert "customers (version 1)" in blocked


def test_erasure_writes_through_the_real_backend_interface(db: Session, world: dict) -> None:
    """The production backend exposes save_upload, not write_bytes. The old code
    guarded on write_bytes and silently skipped the write against the real
    backend — reporting 'completed' with the data untouched. This pins the fix."""

    class _RealShapedStorage:
        def __init__(self) -> None:
            self.files: dict[str, bytes] = {}

        def read_bytes(self, path: str) -> bytes:
            if path not in self.files:
                raise FileNotFoundError(path)
            return self.files[path]

        def save_upload(self, *, relative_path: str, file_bytes: bytes):
            self.files[relative_path] = file_bytes

    storage = _RealShapedStorage()
    ds = _dataset(db, world["project"], storage, "customers", path="d/customers.csv")
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"
    db.refresh(ds)
    assert b"alice@acme.com" not in storage.files[ds.file_path]


def test_an_unreadable_dataset_blocks_completion(db: Session, world: dict) -> None:
    storage = world["storage"]
    _dataset(db, world["project"], storage, "good", path="d/good.csv")
    # A dataset whose file is missing from storage cannot be searched or cleared.
    _dataset(db, world["project"], storage, "missing", path="d/missing.csv", seed=None)
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    # Cannot claim the subject is gone from a file we could not read.
    assert result.status == "partial"
    blocked_names = [b["dataset"] for b in result.report["blocked"]]
    assert "missing" in blocked_names
