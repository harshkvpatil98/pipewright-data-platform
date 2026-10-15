"""The live-source runner (D1, roadmap Phase 20).

Reads every active live source when it is due (each says how often, five
seconds by default), stores what arrived with its position, runs the
source's live recipes and saves its datasets when their interval comes
round. Each source is held under a lease while it is read, so several
runners share the work and never read one source twice at once; a runner
that dies lets its leases run out.

    platform-live-runner --interval 1
    platform-live-runner --once
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
from service_workflows.queue import worker_identity
from shared_python.logging import configure_logging, get_logger

configure_logging(service_name="live-runner", level=settings.log_level)
logger = get_logger(__name__)

COMPONENT = "live-runner"
_stopping = False


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    """Finish the source in hand, then exit."""
    global _stopping
    _stopping = True
    logger.info("live_runner_stopping signal=%s", signum)


def _beat(interval: float, status: str = "running") -> None:
    db = SessionLocal()
    try:
        record_heartbeat(db, component=COMPONENT, host=current_host(), interval_seconds=max(interval, 5.0), status=status)
    finally:
        db.close()


def tick(owner: str) -> int:
    """One pass over the sources that are due. Returns how many were read."""
    from service_extraction.streams import due_sources, run_pass

    db = SessionLocal()
    try:
        due = due_sources(db)
    finally:
        db.close()
    for source_id in due:
        if _stopping:
            break
        db = SessionLocal()
        try:
            result = run_pass(db, source_id, owner=owner, storage_backend=storage_backend, settings=settings)
            if result["stored"] or result["error"] or result["saved"]:
                logger.info("live_source_pass source_id=%s stored=%s saved=%s error=%s",
                            source_id, result["stored"], result["saved"], result["error"])
        except Exception:  # noqa: BLE001 - one source must not stop the rest
            logger.exception("live_source_pass_crashed source_id=%s", source_id)
        finally:
            db.close()
    return len(due)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Pipewright's live sources.")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between looks for a due source when none is (default: 1).")
    parser.add_argument("--once", action="store_true", help="Read what is due once and exit.")
    args = parser.parse_args()
    from api_gateway.plugins import load_enabled

    load_enabled(settings)  # a live recipe or a feed may use what a plugin adds (X1)

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    owner = f"live-{worker_identity(settings)}"
    logger.info("live_runner_started owner=%s interval=%s once=%s", owner, args.interval, args.once)

    if args.once:
        tick(owner)
        return 0
    last_beat = 0.0
    while not _stopping:
        if time.monotonic() - last_beat >= 5:
            _beat(args.interval)
            last_beat = time.monotonic()
        try:
            read = tick(owner)
        except Exception:  # noqa: BLE001 - a pass failure must not kill the runner
            logger.exception("live_runner_tick_failed")
            read = 0
        if read == 0 and not _stopping:
            time.sleep(max(0.2, args.interval))
    _beat(args.interval, status="stopping")
    logger.info("live_runner_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
