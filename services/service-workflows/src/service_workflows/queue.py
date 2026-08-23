"""The run queue.

Enqueueing a run is a database insert, so the API returns immediately and a
worker picks the run up out of band. That is what stops a long extraction from
occupying a web request.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` plus a lease, matching the
approach the scheduler already uses: several workers can poll the same table
without handing the same run to two of them.

A run whose worker dies is failed once its lease expires, not retried. Until
runs are idempotent, replaying one could publish the same data or send the same
notification twice, so the decision to run it again belongs to a person.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_workflows.cron import advance_after_fire, due_workflows
from service_workflows.executor import execute_workflow_run
from service_workflows.models import Workflow, WorkflowRun
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LEASE_SECONDS = 900


def worker_identity(settings: Any | None = None) -> str:
    """Stable id for this worker process, used as the lease owner."""
    configured = getattr(settings, "workflow_worker_id", None) if settings else None
    return str(configured or os.getenv("WORKFLOW_WORKER_ID") or f"worker-{os.getpid()}")


def lease_seconds(settings: Any | None = None) -> int:
    configured = getattr(settings, "workflow_lease_seconds", None) if settings else None
    try:
        return max(60, int(configured or DEFAULT_LEASE_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_LEASE_SECONDS


def enqueue_workflow_run(
    db: Session,
    *,
    workflow: Workflow,
    triggered_by_user_id: uuid.UUID | None,
    trigger: str = "manual",
    parameters: dict[str, Any] | None = None,
    logical_date: datetime | None = None,
) -> WorkflowRun:
    """Queue a run. Returns immediately; a worker executes it."""
    if not workflow.enabled:
        raise BadRequestError("This workflow is disabled.")

    merged = {**(workflow.default_parameters or {}), **(parameters or {})}
    run = WorkflowRun(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        status="queued",
        trigger=trigger,
        parameters_json=merged or None,
        logical_date=logical_date,
        queued_at=datetime.now(UTC),
        triggered_by_user_id=triggered_by_user_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def claim_next_run(db: Session, *, settings: Any | None = None) -> WorkflowRun | None:
    """Take ownership of the oldest queued run, or return None if there is none.

    Only `queued` rows are claimed. A run abandoned by a dead worker is *not*
    picked up here: it may already have published data or sent notifications,
    and replaying it would repeat those effects. `release_stalled_runs` fails
    those instead, so a person decides whether to run them again.

    `FOR UPDATE SKIP LOCKED` lets several workers poll the same table without
    two of them taking the same run.
    """
    now = datetime.now(UTC)
    owner = worker_identity(settings)
    expires = now + timedelta(seconds=lease_seconds(settings))

    statement = (
        select(WorkflowRun)
        .where(WorkflowRun.status == "queued")
        .order_by(WorkflowRun.queued_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    run = db.scalars(statement).first()
    if run is None:
        return None

    run.status = "running"
    run.claim_owner_id = owner[:128]
    run.claim_expires_at = expires
    if run.started_at is None:
        run.started_at = now
    db.commit()
    db.refresh(run)
    return run


def run_next(
    db: Session, *, storage_backend: Any, settings: Any | None = None
) -> WorkflowRun | None:
    """Claim and execute a single run. Returns None when the queue is empty."""
    run = claim_next_run(db, settings=settings)
    if run is None:
        return None

    try:
        return execute_workflow_run(
            db, run=run, storage_backend=storage_backend, settings=settings
        )
    except Exception as exc:  # noqa: BLE001 - a worker must survive any single run
        logger.exception("workflow_run_crashed run_id=%s", run.id)
        return _record_crash(db, run_id=run.id, exc=exc)


def _record_crash(db: Session, *, run_id: uuid.UUID, exc: Exception) -> WorkflowRun | None:
    """Mark a crashed run failed, without letting the bookkeeping crash too.

    The session may be poisoned by the original error, so this rolls back first
    and treats its own failure as non-fatal. If it cannot write, the run keeps
    its lease and is reclaimed once that expires -- the lease is the backstop,
    this is only the fast path.
    """
    try:
        db.rollback()
        crashed = db.get(WorkflowRun, run_id)
        if crashed is None:
            return None

        crashed.status = "failed"
        crashed.finished_at = datetime.now(UTC)
        crashed.error_message = f"Run crashed: {exc.__class__.__name__}"
        crashed.claim_owner_id = None
        crashed.claim_expires_at = None
        db.commit()
        return crashed
    except Exception:  # noqa: BLE001
        logger.exception("workflow_run_crash_bookkeeping_failed run_id=%s", run_id)
        db.rollback()
        return None


def release_stalled_runs(db: Session, *, settings: Any | None = None) -> int:
    """Fail runs whose worker died and whose lease has expired.

    Reclaiming would re-execute a run that may have already had side effects, so
    a stalled run is failed for a human to inspect rather than retried blindly.
    """
    now = datetime.now(UTC)
    stalled = list(
        db.scalars(
            select(WorkflowRun).where(
                WorkflowRun.status == "running",
                WorkflowRun.claim_expires_at.is_not(None),
                WorkflowRun.claim_expires_at <= now,
            )
        ).all()
    )
    for run in stalled:
        logger.warning(
            "workflow_run_stalled run_id=%s owner=%s", run.id, run.claim_owner_id
        )
        run.status = "failed"
        run.finished_at = now
        run.error_message = (
            "The worker executing this run stopped responding and its lease expired."
        )
        run.claim_owner_id = None
        run.claim_expires_at = None
    if stalled:
        db.commit()
    return len(stalled)


def enqueue_due_workflows(db: Session, *, now: datetime | None = None) -> list[WorkflowRun]:
    """Queue a run for every cron workflow whose time has come.

    `next_run_at` is advanced before the run is queued, so a slow tick cannot
    queue the same occurrence twice.
    """
    moment = now or datetime.now(UTC)
    queued: list[WorkflowRun] = []

    for workflow in due_workflows(db, now=moment):
        scheduled_for = workflow.next_run_at
        advance_after_fire(workflow, now=moment)
        db.commit()

        try:
            run = enqueue_workflow_run(
                db,
                workflow=workflow,
                triggered_by_user_id=workflow.created_by_user_id,
                trigger="cron",
                parameters={"scheduled_for": scheduled_for.isoformat()} if scheduled_for else None,
                # The slot, not the moment the worker got to it.
                logical_date=scheduled_for,
            )
        except BadRequestError as exc:
            # A workflow disabled between the query and here; skip it quietly.
            logger.info("workflow_cron_skipped workflow_id=%s reason=%s", workflow.id, exc.detail)
            continue

        logger.info(
            "workflow_cron_queued workflow_id=%s run_id=%s next_run_at=%s",
            workflow.id,
            run.id,
            workflow.next_run_at,
        )
        queued.append(run)

    return queued


def _sweep_freshness(db: Session) -> None:
    """Run the freshness sweep as part of the worker tick.

    Freshness is the only check nothing else can trigger: it asserts that a run
    *happened*, so a run failing to happen is exactly the case it has to catch.
    Best effort -- a sweep that errors must not stop the queue from draining.
    """
    try:
        from service_observability.service import sweep_freshness

        sweep_freshness(db)
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("freshness_sweep_failed")


def _run_due_reports(db: Session, storage_backend: Any) -> None:
    """Generate scheduled reports as part of the worker tick.

    Best effort, like the freshness sweep: a report that fails must not stop
    workflow runs from draining.
    """
    try:
        from service_reporting.service import run_due_reports

        run_due_reports(db, storage_backend)
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("scheduled_reports_failed")


def drain_queue(
    db: Session,
    *,
    storage_backend: Any,
    settings: Any | None = None,
    max_runs: int = 10,
    include_scheduled: bool = True,
) -> list[WorkflowRun]:
    """Execute up to `max_runs` queued runs. One tick of a worker."""
    # Clear out runs abandoned by a dead worker before taking new work, so a
    # stalled run does not sit in "running" indefinitely.
    release_stalled_runs(db, settings=settings)

    # Cron workflows join the same queue as manual runs, so there is one path
    # through execution regardless of what triggered a run.
    if include_scheduled:
        enqueue_due_workflows(db)
        _sweep_freshness(db)
        _run_due_reports(db, storage_backend)

    completed: list[WorkflowRun] = []
    for _ in range(max(1, max_runs)):
        run = run_next(db, storage_backend=storage_backend, settings=settings)
        if run is None:
            break
        completed.append(run)
    return completed


def cancel_run(db: Session, *, project_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowRun:
    """Cancel a run that has not started executing yet."""
    run = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.project_id == project_id)
    )
    if run is None:
        raise NotFoundError("Workflow run not found.")
    if run.status != "queued":
        raise BadRequestError(
            f"Only queued runs can be cancelled; this one is '{run.status}'."
        )

    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    run.claim_owner_id = None
    run.claim_expires_at = None
    db.commit()
    db.refresh(run)
    return run


def queue_depth(db: Session) -> int:
    from sqlalchemy import func

    return db.scalar(
        select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "queued")
    ) or 0


def running_count(db: Session) -> int:
    from sqlalchemy import func

    return db.scalar(
        select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "running")
    ) or 0
