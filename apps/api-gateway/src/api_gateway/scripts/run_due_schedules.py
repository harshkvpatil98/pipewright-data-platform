"""Execute due schedules.

Two modes, one entry point:

* one-shot (default) -- drain due schedules once and exit, for a cron job or a
  systemd timer that owns the cadence.
* ``--loop`` -- run continuously as a supervised process, draining on an
  interval and writing a ``schedule-ticker`` heartbeat each pass so the status
  panel can prove the ticker is alive rather than inferring it from lateness.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from types import FrameType

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.config import settings
from api_gateway.dependencies import SessionLocal, get_storage_backend
from service_observability.runtime import current_host, record_heartbeat
from service_schedules.scheduler_executor import run_due_schedules_once
from shared_python.logging import configure_logging, get_logger

configure_logging(service_name="schedule-ticker", level=settings.log_level)
logger = get_logger(__name__)

_stopping = False


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True
    logger.info("schedule_ticker_stopping signal=%s", signum)


def _drain_once():
    db = SessionLocal()
    try:
        return run_due_schedules_once(
            db, storage_backend=get_storage_backend(), settings=settings
        )
    finally:
        db.close()


def _beat(interval: float, status: str = "running") -> None:
    db = SessionLocal()
    try:
        record_heartbeat(
            db,
            component="schedule-ticker",
            host=current_host(),
            interval_seconds=interval,
            status=status,
        )
    finally:
        db.close()


def _sweep_incidents() -> None:
    """Open/resolve stalled-queue incidents. The ticker is the right home: it
    runs independently of the workflow worker, so it can report the worker's
    death. Best effort -- never fails the ticker loop."""
    from api_gateway.runtime_incidents import sweep_runtime_incidents

    db = SessionLocal()
    try:
        sweep_runtime_incidents(db)
    except Exception:  # noqa: BLE001 - a sweep failure must not stop the ticker
        logger.exception("runtime_incident_sweep_failed")
    finally:
        db.close()


def _sweep_audit() -> None:
    """Enforce the audit retention window. Best effort -- never fails the loop."""
    if settings.audit_retention_days <= 0:
        return
    from api_gateway.audit_center import sweep_audit_entries

    db = SessionLocal()
    try:
        sweep_audit_entries(db, retention_days=settings.audit_retention_days)
    except Exception:  # noqa: BLE001 - a sweep failure must not stop the ticker
        logger.exception("audit_sweep_failed")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute due Pipewright schedules.")
    parser.add_argument(
        "--loop", action="store_true", help="Run continuously instead of once and exit."
    )
    parser.add_argument(
        "--interval", type=float, default=30.0, help="Seconds between passes in --loop (default: 30)."
    )
    args = parser.parse_args()

    if not args.loop:
        summary = _drain_once()
        json.dump(summary.model_dump(mode="json"), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        if summary.failure_count > 0:
            sys.exit(1)
        return

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    logger.info("schedule_ticker_started interval=%s", args.interval)

    while not _stopping:
        _beat(args.interval)
        _sweep_incidents()
        _sweep_audit()
        try:
            summary = _drain_once()
            if summary.triggered_count or summary.failure_count:
                logger.info(
                    "schedule_ticker_pass triggered=%s failed=%s",
                    summary.triggered_count,
                    summary.failure_count,
                )
        except Exception:  # noqa: BLE001 - a pass failure must not kill the ticker
            logger.exception("schedule_ticker_pass_failed")
        if not _stopping:
            time.sleep(max(1.0, args.interval))

    _beat(args.interval, status="stopping")
    logger.info("schedule_ticker_stopped")


if __name__ == "__main__":
    main()
