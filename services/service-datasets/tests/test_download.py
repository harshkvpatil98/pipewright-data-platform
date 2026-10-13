"""Downloading a dataset as CSV or Parquet (adoption-readiness A4, U5).

The properties that matter: a download holds exactly the data of the version
asked for, Parquet round-trips, and the project's row and column policies
apply -- a download must never show more than the policies allow.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.download import download_dataset
from service_enterprise.models import SecurityPolicy
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.contracts import project_role
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.storage.local import LocalStorageBackend

CSV = b"customer,email,amount\nann,ann@example.com,10\nbo,bo@example.com,20\n"


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
def world(db: Session, tmp_path) -> dict:
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    uploaded = ingest_project_file(
        db, project_id=project.id, dataset_name="Customers & orders",
        upload_file=IngestionUpload(file_name="c.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    return {"project": project, "dataset": uploaded.dataset, "user": user, "storage": storage}


def _download(db: Session, world: dict, **kwargs):
    return download_dataset(
        db, world["project"].id, world["dataset"].id, world["user"], world["storage"], **kwargs
    )


def test_csv_holds_the_rows_and_a_safe_file_name(db: Session, world: dict) -> None:
    content, media_type, filename = _download(db, world)
    frame = pd.read_csv(io.BytesIO(content))
    assert list(frame["customer"]) == ["ann", "bo"]
    assert media_type.startswith("text/csv")
    assert filename == "Customers-orders.csv"


def test_parquet_round_trips(db: Session, world: dict) -> None:
    content, _, filename = _download(db, world, export_format="parquet")
    frame = pd.read_parquet(io.BytesIO(content))
    assert list(frame["amount"]) == [10, 20]
    assert filename.endswith(".parquet")


def test_a_version_downloads_by_number(db: Session, world: dict) -> None:
    _, _, filename = _download(db, world, version_number=1)
    assert filename == "Customers-orders-v1.csv"
    with pytest.raises(NotFoundError):
        _download(db, world, version_number=9)


def test_the_projects_policies_apply(db: Session, world: dict) -> None:
    role = project_role(db, world["project"].id, world["user"].id)
    db.add(
        SecurityPolicy(
            project_id=world["project"].id, dataset_id=world["dataset"].id, name="Hide emails",
            role=role, column_rules_json=[{"column": "email", "action": "deny"}],
            row_rules_json=[{"column": "amount", "operator": "greater_than", "value": 15}],
            enabled=True,
        )
    )
    db.commit()
    frame = pd.read_csv(io.BytesIO(_download(db, world)[0]))
    assert "email" not in frame.columns
    assert list(frame["customer"]) == ["bo"]


def test_an_unknown_format_is_refused(db: Session, world: dict) -> None:
    with pytest.raises(BadRequestError):
        _download(db, world, export_format="xlsx")
