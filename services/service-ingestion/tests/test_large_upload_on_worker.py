"""A large upload is read by the background worker (adoption-readiness A7, X3).

The request saves the file and answers at once with the dataset still being
read; the worker reads it as the request would have, and the dataset is then
ready. The threshold is lowered here so a small file stands in for a large
one.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_ingestion import service as ingestion
from service_ingestion.schemas import IngestionUpload
from service_pipeline_runs import background
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

CSV = b"order_id,amount\n1,10\n2,20\n3,30\n"


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


def _queued(db: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "IN_REQUEST_BYTES", 10)
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    storage = LocalStorageBackend(str(tmp_path / "files"))
    answered = ingestion.ingest_project_file(
        db, project_id=project.id, dataset_name="Orders",
        upload_file=IngestionUpload(file_name="orders.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    return answered, storage


def test_a_read_that_fails_before_it_starts_marks_the_dataset(db: Session, tmp_path, monkeypatch) -> None:
    """The stored file gone before the worker got to it: the dataset says it
    could not be read, rather than "being read" for ever (found in A7)."""
    answered, storage = _queued(db, tmp_path, monkeypatch)
    for path in list(storage.list_paths()):
        storage.delete(path)

    finished = background.run_next(db, storage_backend=storage, settings=settings, owner="test-worker")
    assert finished.status == "failed"
    dataset = db.get(Dataset, answered.dataset.id)
    assert dataset.ingestion_status == "failed"
    assert dataset.ingestion_error


def test_a_read_whose_worker_stopped_marks_the_dataset(db: Session, tmp_path, monkeypatch) -> None:
    from datetime import timedelta

    answered, _storage = _queued(db, tmp_path, monkeypatch)
    claimed = background.claim_next(db, owner="dead-worker")
    claimed.claim_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert background.release_stalled(db) == 1
    dataset = db.get(Dataset, answered.dataset.id)
    assert dataset.ingestion_status == "failed"
    assert dataset.ingestion_error == background.STALLED


def test_a_large_file_is_read_by_the_worker(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ingestion, "IN_REQUEST_BYTES", 10)
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    storage = LocalStorageBackend(str(tmp_path / "files"))

    answered = ingestion.ingest_project_file(
        db, project_id=project.id, dataset_name="Orders",
        upload_file=IngestionUpload(file_name="orders.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    assert answered.run.status == "queued"
    assert answered.dataset.ingestion_status != "succeeded"
    assert answered.run.logs_json["events"][-1]["message"] == "Waiting for the background worker."

    finished = background.run_next(db, storage_backend=storage, settings=settings, owner="test-worker")
    assert finished.id == answered.run.id and finished.status == "succeeded"
    dataset = db.get(Dataset, answered.dataset.id)
    assert dataset.ingestion_status == "succeeded"
    assert dataset.row_count == 3


def test_a_large_delimited_file_is_worked_out_from_its_first_part() -> None:
    from service_ingestion.analysis_service import ANALYSIS_SAMPLE_BYTES, _sample

    big = b"id,name\n" + b"".join(f"{i},row {i}\n".encode() for i in range(1_000_000))
    part, full = _sample(big, "orders.csv")
    assert full == len(big) and len(part) <= ANALYSIS_SAMPLE_BYTES
    assert part.endswith(b"\n")  # cut at a line end, never mid-row
    assert _sample(big, "orders.parquet") == (big, None)  # only delimited text is cut
    assert _sample(b"id\n1\n", "small.csv") == (b"id\n1\n", None)
