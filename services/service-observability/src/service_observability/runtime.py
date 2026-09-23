"""Recording and reading background-runtime heartbeats.

The write side is called from inside a worker's loop; the read side is called
by the platform status assembler. Both are deliberately tiny and never raise
on the hot path -- a heartbeat that fails to record must not kill the worker,
and a status read must degrade to "unknown", never to a 500.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.logging import get_logger

from service_observability.models import RuntimeHeartbeat

logger = get_logger(__name__)

# The components the platform expects to be running. Listed here so the status
# panel can show a component that has *never* beaten as "not running" rather
# than silently omitting it -- an absent worker is exactly what we must surface.
EXPECTED_COMPONENTS = ("workflow-worker", "schedule-ticker")

# A beat is stale once it is older than this many times its own interval; the
# floor keeps a fast loop from being called dead on one skipped beat.
STALE_INTERVAL_MULTIPLE = 3
MIN_STALE_SECONDS = 30.0


def current_host() -> str:
    try:
        return socket.gethostname() or "unknown"
    except Exception:  # noqa: BLE001 - hostname lookup is best effort
        return "unknown"


def record_heartbeat(
    db: Session,
    *,
    component: str,
    host: str | None = None,
    interval_seconds: float = 5.0,
    status: str = "running",
    detail: dict | None = None,
    now: datetime | None = None,
) -> None:
    """Upsert this component's beat. Best effort: never raises."""
    moment = now or datetime.now(UTC)
    resolved_host = host or current_host()
    try:
        row = db.scalar(
            select(RuntimeHeartbeat).where(
                RuntimeHeartbeat.component == component,
                RuntimeHeartbeat.host == resolved_host,
            )
        )
        if row is None:
            row = RuntimeHeartbeat(component=component, host=resolved_host)
            db.add(row)
        row.beat_at = moment
        row.interval_seconds = float(interval_seconds)
        row.status = status
        row.detail_json = detail
        db.commit()
    except Exception:  # noqa: BLE001 - a missed beat must not stop the loop
        logger.exception("runtime_heartbeat_record_failed component=%s", component)
        db.rollback()


def _stale_after(interval_seconds: float) -> float:
    return max(MIN_STALE_SECONDS, float(interval_seconds) * STALE_INTERVAL_MULTIPLE)


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def runtime_components(
    db: Session,
    *,
    expected: tuple[str, ...] = EXPECTED_COMPONENTS,
    now: datetime | None = None,
) -> list[dict]:
    """One entry per (component, host) beat, plus a placeholder for any expected
    component that has never beaten, so the panel shows what *should* be running
    even when it is not."""
    moment = now or datetime.now(UTC)
    rows = list(db.scalars(select(RuntimeHeartbeat).order_by(RuntimeHeartbeat.component)).all())

    entries: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        seen.add(row.component)
        beat = _as_utc(row.beat_at)
        age = (moment - beat).total_seconds()
        entries.append(
            {
                "component": row.component,
                "host": row.host,
                "last_beat_at": beat.isoformat(),
                "age_seconds": round(age, 1),
                "interval_seconds": row.interval_seconds,
                "status": row.status,
                "healthy": row.status == "running" and age <= _stale_after(row.interval_seconds),
                "detail": row.detail_json or {},
            }
        )

    for component in expected:
        if component not in seen:
            entries.append(
                {
                    "component": component,
                    "host": None,
                    "last_beat_at": None,
                    "age_seconds": None,
                    "interval_seconds": None,
                    "status": "absent",
                    "healthy": False,
                    "detail": {},
                }
            )

    return entries
