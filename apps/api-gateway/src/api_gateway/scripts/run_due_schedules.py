"""CLI: execute due schedules once (for cron or systemd timers)."""

from __future__ import annotations

import json
import sys

from api_gateway.dependencies import SessionLocal, get_storage_backend
from api_gateway.config import settings
from service_schedules.scheduler_executor import run_due_schedules_once


def main() -> None:
    db = SessionLocal()
    try:
        summary = run_due_schedules_once(db, storage_backend=get_storage_backend(), settings=settings)
        json.dump(summary.model_dump(mode="json"), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        if summary.failure_count > 0:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
