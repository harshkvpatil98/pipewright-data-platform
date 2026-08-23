"""The drift gate: a schema change with a consequence.

Drift has been detected and written down since Phase 01. What it never did was
stop anything. These tests cover the gate that closed that hole, including the
part that matters most -- that a *tolerable* change does not halt a run, or the
gate gets disabled within a week.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_observability.models import Incident
from service_projects.models import Project
from service_quality.models import SchemaDriftEvent
from service_workflows.nodes import NodeContext, execute_node
from shared_python.db import Base

OWNER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _schema(columns: dict[str, str]) -> dict:
    return {
        "columns": [
            {"name": name, "inferred_type": kind, "nullable": False}
            for name, kind in columns.items()
        ],
        "ordered_columns": list(columns),
    }


@pytest.fixture()
def world(db: Session) -> dict:
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()

    baseline = Dataset(
        project_id=project.id,
        name="orders_v1",
        status="ready",
        ingestion_status="succeeded",
        schema_json=_schema({"id": "int", "region": "string", "amount": "float"}),
    )
    current = Dataset(
        project_id=project.id,
        name="orders_v2",
        status="ready",
        ingestion_status="succeeded",
        schema_json=_schema({"id": "int", "amount": "float"}),  # region disappeared
    )
    db.add_all([baseline, current])
    db.commit()
    return {"project": project, "baseline": baseline, "current": current}


def _context(db: Session, project) -> NodeContext:
    now = datetime.now(UTC)
    return NodeContext(
        db=db,
        project_id=project.id,
        current_user=UserRead(
            id=OWNER_ID, username="worker", role="admin", is_active=True, created_at=now, updated_at=now
        ),
        storage_backend=None,
        settings=None,
    )


def test_a_removed_column_fails_the_gate(db: Session, world: dict):
    result = execute_node(
        "drift_gate",
        {
            "dataset_id": str(world["current"].id),
            "baseline_dataset_id": str(world["baseline"].id),
        },
        _context(db, world["project"]),
    )
    assert result.success is False
    assert result.output["drift_severity"] == "breaking"
    assert "region" in result.output["removed_columns"]


def test_failing_the_gate_opens_an_incident(db: Session, world: dict):
    execute_node(
        "drift_gate",
        {
            "dataset_id": str(world["current"].id),
            "baseline_dataset_id": str(world["baseline"].id),
        },
        _context(db, world["project"]),
    )
    db.commit()

    incident = db.query(Incident).one()
    assert incident.source_kind == "drift"
    assert incident.severity == "critical"
    assert incident.dataset_id == world["current"].id


def test_the_gate_records_the_drift_it_found(db: Session, world: dict):
    execute_node(
        "drift_gate",
        {
            "dataset_id": str(world["current"].id),
            "baseline_dataset_id": str(world["baseline"].id),
        },
        _context(db, world["project"]),
    )
    db.commit()
    assert db.query(SchemaDriftEvent).one().severity == "breaking"


def test_a_new_column_alone_does_not_stop_the_run(db: Session, world: dict):
    """Additive change is the common case; halting on it makes the gate useless."""
    widened = Dataset(
        project_id=world["project"].id,
        name="orders_v3",
        status="ready",
        ingestion_status="succeeded",
        schema_json=_schema({"id": "int", "region": "string", "amount": "float", "channel": "string"}),
    )
    db.add(widened)
    db.commit()

    result = execute_node(
        "drift_gate",
        {"dataset_id": str(widened.id), "baseline_dataset_id": str(world["baseline"].id)},
        _context(db, world["project"]),
    )
    assert result.success is True
    assert result.output["drift_severity"] == "compatible"
    assert db.query(Incident).count() == 0


def test_a_stricter_threshold_stops_on_the_additive_change_too(db: Session, world: dict):
    widened = Dataset(
        project_id=world["project"].id,
        name="orders_v3",
        status="ready",
        ingestion_status="succeeded",
        schema_json=_schema({"id": "int", "region": "string", "amount": "float", "channel": "string"}),
    )
    db.add(widened)
    db.commit()

    result = execute_node(
        "drift_gate",
        {
            "dataset_id": str(widened.id),
            "baseline_dataset_id": str(world["baseline"].id),
            "block_on": "compatible",
        },
        _context(db, world["project"]),
    )
    assert result.success is False


def test_an_identical_schema_passes_cleanly(db: Session, world: dict):
    twin = Dataset(
        project_id=world["project"].id,
        name="orders_twin",
        status="ready",
        ingestion_status="succeeded",
        schema_json=world["baseline"].schema_json,
    )
    db.add(twin)
    db.commit()

    result = execute_node(
        "drift_gate",
        {"dataset_id": str(twin.id), "baseline_dataset_id": str(world["baseline"].id)},
        _context(db, world["project"]),
    )
    assert result.success is True
    assert result.message == "No schema change detected."


def test_without_a_baseline_the_gate_reads_recorded_drift(db: Session, world: dict):
    """The common shape: an extraction node upstream already recorded the drift."""
    db.add(
        SchemaDriftEvent(
            project_id=world["project"].id,
            dataset_id=world["current"].id,
            previous_dataset_id=world["baseline"].id,
            severity="breaking",
            summary="Column 'region' was removed.",
            removed_columns=["region"],
        )
    )
    db.commit()

    result = execute_node(
        "drift_gate", {"dataset_id": str(world["current"].id)}, _context(db, world["project"])
    )
    assert result.success is False
    assert "region" in result.message


def test_acknowledged_drift_no_longer_blocks(db: Session, world: dict):
    """Acknowledging is how a person says "yes, I meant that"."""
    db.add(
        SchemaDriftEvent(
            project_id=world["project"].id,
            dataset_id=world["current"].id,
            previous_dataset_id=world["baseline"].id,
            severity="breaking",
            summary="Column 'region' was removed.",
            removed_columns=["region"],
            acknowledged=True,
        )
    )
    db.commit()

    result = execute_node(
        "drift_gate", {"dataset_id": str(world["current"].id)}, _context(db, world["project"])
    )
    assert result.success is True


def test_no_recorded_drift_and_no_baseline_passes(db: Session, world: dict):
    result = execute_node(
        "drift_gate", {"dataset_id": str(world["current"].id)}, _context(db, world["project"])
    )
    assert result.success is True


def test_an_unknown_threshold_is_rejected_as_a_node_failure(db: Session, world: dict):
    result = execute_node(
        "drift_gate",
        {"dataset_id": str(world["current"].id), "block_on": "whenever"},
        _context(db, world["project"]),
    )
    assert result.success is False
    assert "block_on" in result.message


def test_repeated_breaking_drift_is_one_incident(db: Session, world: dict):
    config = {
        "dataset_id": str(world["current"].id),
        "baseline_dataset_id": str(world["baseline"].id),
    }
    execute_node("drift_gate", config, _context(db, world["project"]))
    db.commit()
    execute_node("drift_gate", config, _context(db, world["project"]))
    db.commit()

    assert db.query(Incident).count() == 1
    assert db.query(Incident).one().occurrence_count == 2
