"""Standalone workflow worker.

Runs outside the web process, claims queued workflow runs, and executes them.
Several workers can run at once: claiming uses a row lock plus a lease, so a run
is handed to exactly one worker and a worker that dies releases its run when the
lease expires.

    platform-workflow-worker --interval 5
    platform-workflow-worker --once
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from types import FrameType

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.config import settings
from api_gateway.dependencies import SessionLocal, storage_backend
from service_observability.runtime import current_host, record_heartbeat
from service_workflows.queue import drain_queue, queue_depth, worker_identity
from shared_python.logging import configure_logging, get_logger

configure_logging(service_name="workflow-worker", level=settings.log_level)
logger = get_logger(__name__)

_stopping = False


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    """Finish the run in flight, then exit. Never abandon work mid-execution."""
    global _stopping
    _stopping = True
    logger.info("workflow_worker_stopping signal=%s", signum)


def _beat(interval: float, status: str = "running") -> None:
    """Record this worker's heartbeat. Best effort -- never fails the loop."""
    db = SessionLocal()
    try:
        record_heartbeat(
            db,
            component="workflow-worker",
            host=current_host(),
            interval_seconds=interval,
            status=status,
        )
    finally:
        db.close()


def _retry_webhooks(db) -> None:
    """Make the webhook tries that are due (A8, Y1). Best effort."""
    from service_notifications.senders.webhook_sender import retry_due

    try:
        retry_due(db)
    except Exception:  # noqa: BLE001 - a webhook problem must not stop the worker
        db.rollback()
        logger.exception("webhook_retry_failed")


def tick_background(max_runs: int) -> int:
    """Do queued background runs (large uploads, deliveries, database copies; A7, X3).

    The modules that register them are imported here so a worker knows every
    kind the gateway can queue.
    """
    import service_destinations.copy_database  # noqa: F401 - registers database copies
    import service_destinations.deliver  # noqa: F401 - registers large deliveries
    import service_ingestion.service  # noqa: F401 - registers large uploads
    from service_pipeline_runs import background

    db = SessionLocal()
    try:
        background.release_stalled(db)
        _retry_webhooks(db)
        done = 0
        while done < max_runs and not _stopping:
            run = background.run_next(
                db, storage_backend=storage_backend, settings=settings, owner=worker_identity(settings)
            )
            if run is None:
                break
            done += 1
            logger.info("background_run_finished run_id=%s run_type=%s status=%s", run.id, run.run_type, run.status)
        return done
    finally:
        db.close()


def tick(max_runs: int) -> int:
    processed = tick_background(max_runs)
    db = SessionLocal()
    try:
        completed = drain_queue(
            db, storage_backend=storage_backend, settings=settings, max_runs=max_runs
        )
        for run in completed:
            logger.info(
                "workflow_run_finished run_id=%s status=%s succeeded=%s failed=%s skipped=%s",
                run.id,
                run.status,
                run.nodes_succeeded,
                run.nodes_failed,
                run.nodes_skipped,
            )
        return processed + len(completed)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute queued Pipewright workflow runs.")
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Seconds between polls (default: 5)."
    )
    parser.add_argument(
        "--max-runs", type=int, default=5, help="Runs to execute per poll (default: 5)."
    )
    parser.add_argument("--once", action="store_true", help="Drain the queue once and exit.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    logger.info(
        "workflow_worker_started identity=%s interval=%s once=%s",
        worker_identity(settings),
        args.interval,
        args.once,
    )

    if args.once:
        processed = tick(args.max_runs)
        db = SessionLocal()
        try:
            logger.info("workflow_worker_done processed=%s remaining=%s", processed, queue_depth(db))
        finally:
            db.close()
        return 0

    while not _stopping:
        # Beat before working: even a worker that is busy every poll must still
        # prove it is alive, and a beat at the top of the loop does that.
        _beat(args.interval)
        try:
            processed = tick(args.max_runs)
        except Exception:  # noqa: BLE001 - a poll failure must not kill the worker
            logger.exception("workflow_worker_tick_failed")
            processed = 0

        # Only sleep when idle; a busy queue is drained without an artificial pause.
        if processed == 0 and not _stopping:
            time.sleep(max(0.5, args.interval))

    _beat(args.interval, status="stopping")
    logger.info("workflow_worker_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
