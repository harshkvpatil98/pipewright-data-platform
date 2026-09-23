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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_enterprise.schemas import ErasureCreate
from service_enterprise.service import request_erasure
from service_projects.models import Project
from shared_python.db import Base

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


def test_correction_clears_the_live_base_data_and_completes(db: Session, world: dict) -> None:
    storage = world["storage"]
    _dataset(db, world["project"], storage, "customers", path="d/customers.csv")
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"
    assert result.report["erased"] == ["customers"]
    assert b"alice@acme.com" not in storage.files["d/customers.csv"]  # actually gone
    assert b"bob@acme.com" in storage.files["d/customers.csv"]  # others untouched


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


def test_a_correction_over_a_derived_dataset_still_clears_it(db: Session, world: dict) -> None:
    # Correction is not the strict historical claim, so it may clear the derived
    # live file too and complete.
    storage = world["storage"]
    _dataset(db, world["project"], storage, "derived", path="d/derived.csv", derived=True)
    db.commit()
    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="correction"),
        _read(world["owner"]), storage,
    )
    assert result.status == "completed"
    assert b"alice@acme.com" not in storage.files["d/derived.csv"]


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
