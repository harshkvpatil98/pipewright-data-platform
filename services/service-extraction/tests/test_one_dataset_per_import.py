"""An import writes every run into one dataset (adoption-readiness A4, U1).

Before, each run created a new dataset, so a nightly import made 365 a year.
These run a real import twice against a SQLite file and check the second run
is a new version of the same dataset, carrying the new rows.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_extraction.extract import run_extraction_job
from service_extraction.models import ExtractionConnection, ExtractionJob
from service_projects.models import Project
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

OWNER_ID = uuid.UUID("0e0e0e0e-0e0e-0e0e-0e0e-0e0e0e0e0e0e")
SETTINGS = SimpleNamespace(max_upload_size_bytes=25 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)


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
def source(tmp_path) -> str:
    path = str(tmp_path / "shop.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL)")
        conn.executemany("INSERT INTO orders VALUES (?, ?)", [(1, 10.0), (2, 20.0)])
    return path


@pytest.fixture()
def world(db: Session, source: str, tmp_path) -> dict:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.flush()
    project = Project(name="Shop", slug="shop", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()
    connection = ExtractionConnection(
        project_id=project.id, name="Shop DB", connector_type="sqlite", config_json={"file_path": source}
    )
    db.add(connection)
    db.flush()
    job = ExtractionJob(
        project_id=project.id, connection_id=connection.id, name="Orders",
        source_kind="table", source_table="orders", load_mode="full_refresh",
    )
    db.add(job)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    return {"project": project, "job": job, "user": user, "storage": LocalStorageBackend(str(tmp_path / "storage"))}


def _run(db: Session, world: dict):
    return run_extraction_job(
        db, project_id=world["project"].id, job_id=world["job"].id, current_user=world["user"],
        storage_backend=world["storage"], settings=SETTINGS,
    )


def _versions(db: Session, dataset_id) -> int:
    return int(db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)))


def test_a_second_run_is_a_new_version_of_the_same_dataset(db: Session, world: dict, source: str) -> None:
    first = _run(db, world)
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO orders VALUES (3, 30.0)")
    second = _run(db, world)

    assert second.dataset_id == first.dataset_id
    assert db.scalar(select(func.count()).select_from(Dataset)) == 1
    assert _versions(db, first.dataset_id) == 2
    assert db.get(Dataset, first.dataset_id).row_count == 3


def test_a_renamed_dataset_keeps_its_name(db: Session, world: dict) -> None:
    first = _run(db, world)
    dataset = db.get(Dataset, first.dataset_id)
    dataset.name = "Orders (finance copy)"
    db.commit()
    _run(db, world)
    assert db.get(Dataset, first.dataset_id).name == "Orders (finance copy)"


def test_a_deleted_dataset_is_started_again(db: Session, world: dict) -> None:
    first = _run(db, world)
    db.delete(db.get(Dataset, first.dataset_id))
    db.commit()
    second = _run(db, world)
    assert second.dataset_id != first.dataset_id
    assert _versions(db, second.dataset_id) == 1
