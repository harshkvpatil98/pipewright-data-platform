"""Imports from connectors other than the SQL databases (adoption-readiness A4, U2).

Runs against the server-files connector, which reads real files from a real
folder (tier 2), so nothing here is mocked: connect, list what is there,
import, run again, and bring only what is new.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_extraction.extract import run_extraction_job
from service_extraction.models import ExtractionConnection
from service_extraction.schemas import ExtractionConnectionCreate, ExtractionJobCreate
from service_extraction.service import create_connection, create_job, discover_tables, list_connections
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.storage.local import LocalStorageBackend

OWNER_ID = uuid.UUID("0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f")
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
def incoming(tmp_path, monkeypatch):
    root = tmp_path / "server-files"
    folder = root / "incoming"
    folder.mkdir(parents=True)
    monkeypatch.setenv("SERVER_FILES_ROOT", str(root))
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    (folder / "orders-1.csv").write_text("order_id,amount\n1,10\n2,20\n")
    return folder


@pytest.fixture()
def world(db: Session, tmp_path) -> dict:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.flush()
    project = Project(name="Shop", slug="shop", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    return {"project": project, "user": user, "storage": LocalStorageBackend(str(tmp_path / "storage"))}


def _connect(db, world, connector_type: str, config: dict):
    return create_connection(
        db, world["project"].id,
        ExtractionConnectionCreate(name=f"{connector_type} source", connector_type=connector_type, config=config),
        world["user"],
    )


def _job(db, world, connection_id, **fields):
    payload = ExtractionJobCreate(connection_id=connection_id, name="Orders", source_kind="stream", **fields)
    return create_job(db, world["project"].id, payload, world["user"])


def _run(db, world, job_id):
    return run_extraction_job(
        db, project_id=world["project"].id, job_id=job_id, current_user=world["user"],
        storage_backend=world["storage"], settings=SETTINGS,
    )


def test_a_folder_lists_its_files_and_one_imports_into_a_dataset(db, world, incoming) -> None:
    connection = _connect(db, world, "local_files", {"directory": "incoming", "pattern": "*.csv"})
    listed = discover_tables(db, world["project"].id, connection.id, world["user"])
    assert listed.can_list and listed.can_resume
    assert [item.name for item in listed.items] == ["orders-1.csv"]

    stream = {"name": "orders-1.csv", "namespace": None, "kind": "file", "detail": listed.items[0].detail}
    job = _job(db, world, connection.id, stream=stream)
    first = _run(db, world, job.id)
    second = _run(db, world, job.id)

    assert first.total_rows == 2
    assert second.dataset_id == first.dataset_id
    count = db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == first.dataset_id))
    assert count == 2


def test_only_new_rows_brings_the_files_that_arrived_since(db, world, incoming) -> None:
    connection = _connect(db, world, "local_files", {"directory": "incoming", "pattern": "*.csv"})
    job = _job(db, world, connection.id, stream=None, load_mode="incremental_append")
    first = _run(db, world, job.id)
    assert first.total_rows == 2

    time.sleep(0.05)  # a later modification time than the first file
    newer = incoming / "orders-2.csv"
    newer.write_text("order_id,amount\n3,30\n")
    later = time.time() + 5
    os.utime(newer, (later, later))

    second = _run(db, world, job.id)
    assert second.rows_extracted == 1
    assert second.total_rows == 3
    assert second.dataset_id == first.dataset_id
    assert db.get(Dataset, first.dataset_id).row_count == 3


def test_a_connectors_secret_is_encrypted_and_never_returned(db, world, incoming) -> None:
    created = _connect(db, world, "s3", {"bucket": "b", "access_key_id": "AKIA", "secret_access_key": "hunter2"})
    stored = db.get(ExtractionConnection, created.id).config_json
    assert stored["secret_access_key"] != "hunter2"
    assert created.config_json["secret_access_key"] == "***"
    listed = list_connections(db, world["project"].id, world["user"]).items[0]
    assert listed.config_json["secret_access_key"] == "***"


def test_settings_are_checked_against_the_connector(db, world, incoming) -> None:
    with pytest.raises(BadRequestError, match="no setting"):
        _connect(db, world, "local_files", {"directory": "incoming", "colour": "blue"})
    with pytest.raises(BadRequestError):
        _connect(db, world, "s3", {"bucket": "b"})  # the keys are required


def test_shaping_during_the_import_is_for_databases(db, world, incoming) -> None:
    connection = _connect(db, world, "local_files", {"directory": "incoming"})
    with pytest.raises(BadRequestError, match="Studio"):
        _job(db, world, connection.id, stream=None, steps=[{"step_type": "drop_null_rows", "config": {"how": "any"}}])


def test_a_connector_this_deployment_cannot_run_says_why(db, world, incoming) -> None:
    from service_connectors import specs

    missing_driver = next(spec for spec in specs() if not spec.available)
    with pytest.raises(BadRequestError, match="needs|not available|no client"):
        _connect(db, world, missing_driver.type, {})
