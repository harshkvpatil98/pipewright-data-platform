"""Long work done by the worker instead of the request (adoption-readiness A7, X3).

A large upload or a database copy can take minutes. Inside a request it would
outlast the proxy's timeout and hold a gateway, so the request queues a run
and answers at once; the background worker (the workflow worker's process)
claims it, does the work, and writes progress to the run as it goes. The run
is an ordinary run: the Runs page shows it, and the page that started it
watches it until it finishes.

A service registers what to do for its run type with `register`. A run whose
worker stopped is failed when its lease runs out, not repeated: a copy that
wrote half its rows should be looked at, not run again unseen.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from service_pipeline_runs.models import PipelineRun
from shared_python.errors import ApplicationError
from shared_python.lease import kept
from shared_python.logging import get_logger

logger = get_logger(__name__)

#: How long a worker holds a run before another may treat it as stalled. A
#: working worker renews it every quarter of this (`shared_python.lease`), so
#: only a worker that stopped loses it, and its run is failed within minutes.
LEASE_SECONDS = 180

Handler = Callable[[Session, PipelineRun, Any, Any], None]
#: What else to mark when a run fails outside its handler's own care (an
#: unexpected error, a stopped worker): the dataset a large upload was for.
OnFail = Callable[[Session, PipelineRun, str], None]
_HANDLERS: dict[str, Handler] = {}
_ON_FAIL: dict[str, OnFail] = {}

#: What a run whose worker stopped says (A7).
STALLED = "The background worker stopped before this finished. Start it again to finish it."


def register(run_type: str, handler: Handler, *, on_fail: OnFail | None = None) -> None:
    """What the worker does for a queued run of this type, and what to mark if it fails."""
    _HANDLERS[run_type] = handler
    if on_fail is not None:
        _ON_FAIL[run_type] = on_fail


def _after_failure(db: Session, run: PipelineRun, message: str) -> None:
    """Best effort: a failure to mark the rest must not hide the run's own failure."""
    hook = _ON_FAIL.get(run.run_type)
    if hook is None:
        return
    try:
        hook(db, run, message)
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("background_on_fail_failed run_id=%s run_type=%s", run.id, run.run_type)
        db.rollback()


def handled_types() -> list[str]:
    return sorted(_HANDLERS)


def event(stage: str, message: str, **details: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"stage": stage, "message": message, "recorded_at": datetime.now(UTC).isoformat()}
    if details:
        entry["details"] = details
    return entry


def queue(
    db: Session,
    *,
    run: PipelineRun,
    request: dict[str, Any],
    message: str,
) -> PipelineRun:
    """Hand a run to the worker: it stays queued with what to do."""
    run.status = "queued"
    run.request_json = request
    events = list((run.logs_json or {}).get("events", []))
    events.append(event("queued", message))
    run.logs_json = {**(run.logs_json or {}), "events": events}
    db.commit()
    db.refresh(run)
    return run


def progress(db: Session, run: PipelineRun, stage: str, message: str, **details: Any) -> None:
    """Record how far the work has got, and keep the lease while it does."""
    events = list((run.logs_json or {}).get("events", []))
    events.append(event(stage, message, **details))
    run.logs_json = {**(run.logs_json or {}), "events": events}
    if run.claim_expires_at is not None:
        run.claim_expires_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    db.commit()


def claim_next(db: Session, *, owner: str) -> PipelineRun | None:
    """Take the oldest queued run of a registered type, or None."""
    types = handled_types()
    if not types:
        return None
    statement = (
        select(PipelineRun)
        .where(
            PipelineRun.status == "queued",
            PipelineRun.request_json.is_not(None),
            PipelineRun.run_type.in_(types),
        )
        .order_by(PipelineRun.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    run = db.scalars(statement).first()
    if run is None:
        return None
    now = datetime.now(UTC)
    run.status = "running"
    run.started_at = run.started_at or now
    run.claim_owner_id = owner[:128]
    run.claim_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    db.refresh(run)
    return run


def run_next(db: Session, *, storage_backend: Any, settings: Any, owner: str) -> PipelineRun | None:
    """Claim one queued run and do it. Returns the run, or None when none waits."""
    run = claim_next(db, owner=owner)
    if run is None:
        return None
    handler = _HANDLERS[run.run_type]
    try:
        # A write of millions of rows reports no progress for minutes; the
        # lease is kept from a side thread so another worker does not fail
        # it as stalled while it works.
        with kept(db.get_bind(), table=PipelineRun.__table__, row_id=run.id, owner=run.claim_owner_id,
                  lease_seconds=LEASE_SECONDS):
            handler(db, run, storage_backend, settings)
    except ApplicationError as exc:
        db.rollback()
        _fail(db, run.id, str(exc.detail))
    except Exception:  # noqa: BLE001 - a worker must outlive any one run
        logger.exception("background_run_crashed run_id=%s run_type=%s", run.id, run.run_type)
        db.rollback()
        _fail(db, run.id, "This stopped because of an unexpected error on the server. The details are in its log.")
    finished = db.get(PipelineRun, run.id)
    if finished is not None:
        finished.claim_owner_id = None
        finished.claim_expires_at = None
        db.commit()
    return finished


def _fail(db: Session, run_id: uuid.UUID, message: str) -> None:
    run = db.get(PipelineRun, run_id)
    if run is None or run.status in ("succeeded", "failed"):
        return
    events = list((run.logs_json or {}).get("events", []))
    events.append(event("failed", message))
    run.status = "failed"
    run.completed_at = datetime.now(UTC)
    run.logs_json = {**(run.logs_json or {}), "events": events}
    run.summary_json = {**(run.summary_json or {}), "error": message}
    db.commit()
    _after_failure(db, run, message)


def release_stalled(db: Session, *, now: datetime | None = None) -> int:
    """Fail runs whose worker stopped and whose lease ran out. Returns how many."""
    moment = now or datetime.now(UTC)
    stalled = db.scalars(
        select(PipelineRun).where(
            PipelineRun.status == "running",
            PipelineRun.claim_expires_at.is_not(None),
            PipelineRun.claim_expires_at <= moment,
        )
    ).all()
    released = []
    for run in stalled:
        events = [*list((run.logs_json or {}).get("events", [])), event("failed", STALLED)]
        # Claimed with a condition the database checks as it writes: a run
        # whose worker renewed or finished it since the read is left alone.
        changed = db.execute(
            update(PipelineRun)
            .where(
                PipelineRun.id == run.id,
                PipelineRun.status == "running",
                PipelineRun.claim_expires_at <= moment,
            )
            .values(
                status="failed", completed_at=moment, claim_owner_id=None, claim_expires_at=None,
                logs_json={**(run.logs_json or {}), "events": events},
                summary_json={**(run.summary_json or {}), "error": STALLED},
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if changed:
            released.append(run)
    db.commit()
    for run in released:
        db.refresh(run)
        _after_failure(db, run, STALLED)
    return len(released)
