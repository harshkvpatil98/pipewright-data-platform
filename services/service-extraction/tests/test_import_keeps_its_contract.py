"""An import whose source loses a promised column is stopped (Phase 19, C1).

Before, the schema change was a warning and the new rows replaced the old
regardless. These run a real import against a SQLite file: once to make the
dataset, then with a contract after the source table loses a column.
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
from service_pipeline_runs.models import PipelineRun
from service_projects.models import Project
from service_quality.data_contracts import ContractBroken, draft_terms, save_contract
from service_quality.models import DataContractProblem
from service_quality.schemas_contracts import DataContractWrite
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

OWNER_ID = uuid.UUID("0e0e0e0e-0e0e-0e0e-0e0e-0e0e0e0e0e0f")
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
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL, email TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, 10.0, "a@x.com"), (2, 20.0, "b@x.com")])
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


def test_a_source_that_loses_a_promised_column_is_stopped(db: Session, world: dict, source: str) -> None:
    first = _run(db, world)
    dataset = db.get(Dataset, first.dataset_id)
    save_contract(
        db, world["project"].id, dataset.id,
        DataContractWrite(enforcement="stop", terms=draft_terms(dataset)), world["user"], world["storage"],
    )
    with sqlite3.connect(source) as conn:
        conn.execute("ALTER TABLE orders DROP COLUMN email")

    with pytest.raises(ContractBroken) as stopped:
        _run(db, world)
    assert "The column 'email' is missing." in stopped.value.detail

    db.expire_all()
    assert "email" in [column["name"] for column in db.get(Dataset, dataset.id).schema_json["columns"]]
    assert db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)) == 1
    job = db.get(ExtractionJob, world["job"].id)
    assert job.last_run_status == "failed" and "breaks the contract" in job.last_error_message
    [problem] = db.scalars(select(DataContractProblem)).all()
    assert (problem.outcome, problem.source_type, problem.source_name) == ("stopped", "import", "Orders")
    run = db.scalars(select(PipelineRun).where(PipelineRun.status == "failed")).one()
    assert run.logs_json["events"][-1]["message"] == "Stopped while checking the rows against the contract."

    # The source puts the column back, and the next import keeps the contract.
    with sqlite3.connect(source) as conn:
        conn.execute("ALTER TABLE orders ADD COLUMN email TEXT")
        conn.execute("UPDATE orders SET email = 'c@x.com'")
    _run(db, world)
    db.expire_all()
    assert db.get(DataContractProblem, problem.id).resolved_at is not None
