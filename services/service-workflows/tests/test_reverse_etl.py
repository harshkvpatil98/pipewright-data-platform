"""Reverse ETL: cleaned data landing where people actually work.

The last mile. A dataset nobody opens is worth nothing, so this writes one back
out through any connector that declares it can be written to.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.schemas import UserRead
from service_connectors.formats import read_bytes
from service_datasets.models import Dataset
from service_projects.models import Project
from service_workflows.nodes import NodeContext, execute_node
from shared_python.db import Base

OWNER_ID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


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


class _Storage:
    """The bytes a dataset's stored artifact would have."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read_bytes(self, _path: str) -> bytes:
        return self._payload


@pytest.fixture()
def world(db: Session) -> dict:
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()

    dataset = Dataset(
        project_id=project.id,
        name="clean_orders",
        status="ready",
        ingestion_status="succeeded",
        file_path="datasets/clean_orders.csv",
        file_type="csv",
    )
    db.add(dataset)
    db.commit()
    return {"project": project, "dataset": dataset}


def _context(db: Session, project: Project) -> NodeContext:
    now = datetime.now(UTC)
    frame = pd.DataFrame({"id": [1, 2], "region": ["north", "south"], "total": [10.0, 20.0]})
    return NodeContext(
        db=db,
        project_id=project.id,
        current_user=UserRead(
            id=OWNER_ID, username="worker", role="admin", is_active=True,
            created_at=now, updated_at=now,
        ),
        storage_backend=_Storage(frame.to_csv(index=False).encode()),
        settings=None,
    )


def test_a_dataset_is_written_out_through_a_connector(db: Session, world: dict, tmp_path: Path):
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "local_files",
            "config": {"directory": str(tmp_path)},
            "target": "exports/orders.csv",
            "mode": "replace",
        },
        _context(db, world["project"]),
    )

    assert result.success, result.message
    assert result.output["rows_written"] == 2
    written = tmp_path / "exports" / "orders.csv"
    assert written.exists()
    assert len(read_bytes(written.read_bytes(), format="csv")) == 2


def test_it_can_write_a_typed_format(db: Session, world: dict, tmp_path: Path):
    """The reason for having Parquet at all: the types survive the trip."""
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "local_files",
            "config": {"directory": str(tmp_path)},
            "target": "orders.parquet",
        },
        _context(db, world["project"]),
    )

    assert result.success, result.message
    back = read_bytes((tmp_path / "orders.parquet").read_bytes(), format="parquet")
    assert pd.api.types.is_float_dtype(back["total"])


def test_appending_adds_to_what_is_there(db: Session, world: dict, tmp_path: Path):
    config = {
        "dataset_id": str(world["dataset"].id),
        "connector_type": "local_files",
        "config": {"directory": str(tmp_path)},
        "target": "log.csv",
    }
    execute_node("reverse_etl", config, _context(db, world["project"]))
    result = execute_node(
        "reverse_etl", {**config, "mode": "append"}, _context(db, world["project"])
    )
    assert result.output["rows_written"] == 4


def test_a_connector_that_cannot_be_written_to_is_refused(db: Session, world: dict):
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "rest_api",
            "config": {"base_url": "https://example.com"},
            "target": "/orders",
        },
        _context(db, world["project"]),
    )
    assert result.success is False
    assert "read but not written to" in result.message


def test_an_unknown_connector_fails_the_node_not_the_run(db: Session, world: dict):
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "teleporter",
            "config": {},
            "target": "x",
        },
        _context(db, world["project"]),
    )
    assert result.success is False
    assert "teleporter" in result.message


def test_a_missing_target_is_reported_clearly(db: Session, world: dict, tmp_path: Path):
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "local_files",
            "config": {"directory": str(tmp_path)},
        },
        _context(db, world["project"]),
    )
    assert result.success is False
    assert "target" in result.message


def test_the_connector_config_is_validated_before_anything_is_written(
    db: Session, world: dict
):
    result = execute_node(
        "reverse_etl",
        {
            "dataset_id": str(world["dataset"].id),
            "connector_type": "local_files",
            "config": {"directory": "relative/path"},
            "target": "out.csv",
        },
        _context(db, world["project"]),
    )
    assert result.success is False
