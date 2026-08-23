"""A run records its numbers, so "was that normal?" has an answer next time.

The capture lives in the executor rather than in each node handler: metric
history only exists if something writes to it on *every* run, and five handlers
each remembering to do it is five chances to forget.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_observability.models import DatasetMetric
from service_projects.models import Project
from service_workflows import executor as executor_module
from service_workflows.executor import execute_workflow_run
from service_workflows.models import Workflow, WorkflowNode, WorkflowRun
from service_workflows.nodes import NodeResult
from shared_python.db import Base

OWNER_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

PROFILE = {
    "row_count": 500,
    "column_count": 3,
    "duplicate_row_percentage": 0.0,
    "completeness_score": 97.5,
    "columns": [{"name": "email", "null_percentage": 2.5, "unique_count": 495}],
}


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
def actor(monkeypatch: pytest.MonkeyPatch) -> UserRead:
    now = datetime.now(UTC)
    user = UserRead(
        id=OWNER_ID, username="worker", role="admin", is_active=True, created_at=now, updated_at=now
    )
    monkeypatch.setattr(executor_module, "_actor_for_run", lambda *_a, **_k: user)
    return user


@pytest.fixture()
def world(db: Session) -> dict:
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()

    dataset = Dataset(
        project_id=project.id,
        name="orders",
        status="ready",
        ingestion_status="succeeded",
        profile_json=PROFILE,
    )
    db.add(dataset)
    db.flush()

    workflow = Workflow(project_id=project.id, name="nightly", trigger_type="manual", enabled=True)
    db.add(workflow)
    db.flush()
    db.add(
        WorkflowNode(
            workflow_id=workflow.id,
            project_id=project.id,
            node_key="extract",
            name="Extract",
            node_type="extraction",
            config_json={},
        )
    )
    run = WorkflowRun(
        workflow_id=workflow.id,
        project_id=project.id,
        status="queued",
        trigger="cron",
        logical_date=datetime(2026, 3, 1, tzinfo=UTC),
        queued_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    return {"project": project, "dataset": dataset, "workflow": workflow, "run": run}


def _handler(output: dict, *, success: bool = True):
    def _execute(_node_type, _config, _context) -> NodeResult:
        return NodeResult(success=success, message="ok", output=output)

    return _execute


def test_a_successful_node_records_the_datasets_metrics(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        executor_module, "execute_node", _handler({"dataset_id": str(world["dataset"].id)})
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)

    metrics = db.query(DatasetMetric).all()
    assert {metric.metric_key for metric in metrics} == {
        "row_count",
        "column_count",
        "duplicate_row_percentage",
        "completeness_score",
        "null_percentage",
        "unique_count",
    }
    assert next(m for m in metrics if m.metric_key == "row_count").value == 500.0


def test_captured_metrics_carry_the_runs_slot_not_the_wall_clock(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    """A backfill for March must chart against March."""
    monkeypatch.setattr(
        executor_module, "execute_node", _handler({"dataset_id": str(world["dataset"].id)})
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)

    metric = db.query(DatasetMetric).first()
    assert metric is not None
    assert metric.logical_date.replace(tzinfo=UTC) == datetime(2026, 3, 1, tzinfo=UTC)
    assert metric.workflow_run_id == world["run"].id


def test_a_failed_node_records_nothing(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        executor_module,
        "execute_node",
        _handler({"dataset_id": str(world["dataset"].id)}, success=False),
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)
    assert db.query(DatasetMetric).count() == 0


def test_a_node_that_produces_no_dataset_records_nothing(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(executor_module, "execute_node", _handler({"message_sent": True}))
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)
    assert db.query(DatasetMetric).count() == 0


def test_an_unprofiled_dataset_does_not_fail_the_run(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    """Capture is a courtesy; a run that did its job must still succeed."""
    bare = Dataset(
        project_id=world["project"].id, name="bare", status="ready", ingestion_status="succeeded"
    )
    db.add(bare)
    db.commit()

    monkeypatch.setattr(executor_module, "execute_node", _handler({"dataset_id": str(bare.id)}))
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)

    db.refresh(world["run"])
    assert world["run"].status == "succeeded"
    assert db.query(DatasetMetric).count() == 0


def test_a_dataset_id_pointing_nowhere_does_not_fail_the_run(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        executor_module, "execute_node", _handler({"dataset_id": str(uuid.uuid4())})
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)

    db.refresh(world["run"])
    assert world["run"].status == "succeeded"


def test_a_run_records_what_it_cost(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    """'The bill went up' is unanswerable without attributing work to a workflow."""
    from service_enterprise.models import UsageRecord

    monkeypatch.setattr(
        executor_module,
        "execute_node",
        _handler({"dataset_id": str(world["dataset"].id), "row_count": 500}),
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)

    usage = db.query(UsageRecord).one()
    assert usage.subject_type == "workflow"
    assert usage.subject_id == world["workflow"].id
    assert usage.rows_processed == 500
    assert usage.compute_ms >= 0


def test_a_failed_node_records_no_usage(
    db: Session, world: dict, actor: UserRead, monkeypatch: pytest.MonkeyPatch
):
    from service_enterprise.models import UsageRecord

    monkeypatch.setattr(
        executor_module, "execute_node", _handler({"row_count": 500}, success=False)
    )
    execute_workflow_run(db, run=world["run"], storage_backend=None, settings=None)
    assert db.query(UsageRecord).count() == 0
