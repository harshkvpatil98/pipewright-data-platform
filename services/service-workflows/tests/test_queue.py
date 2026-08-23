"""Run queue tests: enqueue, claim, stalled-lease handling, cancel."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_workflows.models import Workflow, WorkflowRun
from service_workflows.queue import (
    cancel_run,
    release_stalled_runs,
    claim_next_run,
    enqueue_workflow_run,
    queue_depth,
    running_count,
    worker_identity,
)
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError


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


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@pytest.fixture()
def workflow(db: Session) -> Workflow:
    row = Workflow(
        project_id=uuid.uuid4(),
        name="nightly",
        trigger_type="manual",
        enabled=True,
        default_parameters={"region": "eu"},
    )
    db.add(row)
    db.commit()
    return row


def test_enqueue_creates_a_queued_run(db: Session, workflow: Workflow) -> None:
    run = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)

    assert run.status == "queued"
    assert run.queued_at is not None
    assert run.started_at is None
    assert queue_depth(db) == 1


def test_enqueue_merges_workflow_defaults_with_run_parameters(
    db: Session, workflow: Workflow
) -> None:
    run = enqueue_workflow_run(
        db, workflow=workflow, triggered_by_user_id=None, parameters={"day": "2026-01-01"}
    )
    assert run.parameters_json == {"region": "eu", "day": "2026-01-01"}


def test_run_parameters_override_workflow_defaults(db: Session, workflow: Workflow) -> None:
    run = enqueue_workflow_run(
        db, workflow=workflow, triggered_by_user_id=None, parameters={"region": "us"}
    )
    assert run.parameters_json["region"] == "us"


def test_disabled_workflow_cannot_be_queued(db: Session, workflow: Workflow) -> None:
    workflow.enabled = False
    db.commit()

    with pytest.raises(BadRequestError, match="disabled"):
        enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)


def test_claim_marks_the_run_running_and_takes_a_lease(db: Session, workflow: Workflow) -> None:
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)

    claimed = claim_next_run(db)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.claim_owner_id == worker_identity(None)
    assert claimed.started_at is not None
    # SQLite returns naive datetimes where Postgres returns aware ones, so
    # compare on a common footing rather than assuming either.
    assert _as_utc(claimed.claim_expires_at) > datetime.now(UTC)


def test_claim_returns_none_when_the_queue_is_empty(db: Session) -> None:
    assert claim_next_run(db) is None


def test_a_running_run_with_a_live_lease_is_not_reclaimed(
    db: Session, workflow: Workflow
) -> None:
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    first = claim_next_run(db)
    assert first is not None

    # Nothing else is queued and the lease is still valid.
    assert claim_next_run(db) is None


def test_stalled_run_is_failed_rather_than_replayed(db: Session, workflow: Workflow) -> None:
    """A run abandoned mid-flight may already have published; do not repeat it."""
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    claimed = claim_next_run(db)
    assert claimed is not None

    claimed.claim_owner_id = "dead-worker"
    claimed.claim_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    released = release_stalled_runs(db)

    db.refresh(claimed)
    assert released == 1
    assert claimed.status == "failed"
    assert "lease expired" in claimed.error_message
    # It is not handed back out to a worker.
    assert claim_next_run(db) is None


def test_a_live_lease_is_left_alone(db: Session, workflow: Workflow) -> None:
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    claimed = claim_next_run(db)
    assert claimed is not None

    assert release_stalled_runs(db) == 0
    db.refresh(claimed)
    assert claimed.status == "running"


def test_runs_are_claimed_oldest_first(db: Session, workflow: Workflow) -> None:
    first = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    second = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    # Make the ordering unambiguous regardless of clock resolution.
    first.queued_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    claimed = claim_next_run(db)
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.id != second.id


def test_cancel_removes_a_queued_run_from_the_queue(db: Session, workflow: Workflow) -> None:
    run = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)

    cancelled = cancel_run(db, project_id=workflow.project_id, run_id=run.id)

    assert cancelled.status == "cancelled"
    assert cancelled.finished_at is not None
    assert queue_depth(db) == 0
    assert claim_next_run(db) is None


def test_cancelling_a_running_run_is_rejected(db: Session, workflow: Workflow) -> None:
    run = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    claim_next_run(db)

    with pytest.raises(BadRequestError, match="Only queued runs"):
        cancel_run(db, project_id=workflow.project_id, run_id=run.id)


def test_cancelling_across_projects_is_rejected(db: Session, workflow: Workflow) -> None:
    """Project scoping is enforced on the run, not just on the parent workflow."""
    run = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)

    with pytest.raises(NotFoundError):
        cancel_run(db, project_id=uuid.uuid4(), run_id=run.id)


def test_queue_counters_reflect_state(db: Session, workflow: Workflow) -> None:
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    assert queue_depth(db) == 2
    assert running_count(db) == 0

    claim_next_run(db)
    assert queue_depth(db) == 1
    assert running_count(db) == 1


def test_worker_identity_is_stable_within_a_process() -> None:
    assert worker_identity(None) == worker_identity(None)


def test_settings_can_name_the_worker() -> None:
    class Settings:
        workflow_worker_id = "etl-worker-3"

    assert worker_identity(Settings()) == "etl-worker-3"


def test_cancelled_runs_are_not_executed_later(db: Session, workflow: Workflow) -> None:
    run = enqueue_workflow_run(db, workflow=workflow, triggered_by_user_id=None)
    cancel_run(db, project_id=workflow.project_id, run_id=run.id)

    assert claim_next_run(db) is None
    assert db.get(WorkflowRun, run.id).status == "cancelled"
