from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from service_schedules.models import ScheduledOperation


def clear_schedule_execution_lease(row: ScheduledOperation) -> None:
    row.claim_owner_id = None
    row.claim_acquired_at = None
    row.claim_expires_at = None


def resolve_schedule_timezone(timezone_name: str | None) -> ZoneInfo:
    """Resolve stored timezone name to ZoneInfo; invalid or empty values fall back to UTC."""
    if not timezone_name or not str(timezone_name).strip():
        return ZoneInfo("UTC")
    name = str(timezone_name).strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def compute_first_next_run_utc(cron_expression: str, tz: ZoneInfo, *, now_utc: datetime | None = None) -> datetime:
    """Next cron occurrence strictly after *now* in the schedule timezone, returned in UTC."""
    base_utc = now_utc or datetime.now(UTC)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=UTC)
    local_now = base_utc.astimezone(tz)
    itr = croniter(cron_expression, local_now)
    next_local = itr.get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=tz)
    else:
        next_local = next_local.astimezone(tz)
    return next_local.astimezone(UTC)


def compute_next_run_after_utc(
    cron_expression: str,
    tz: ZoneInfo,
    after_instant_utc: datetime,
) -> datetime:
    """Next cron occurrence strictly after *after_instant_utc* (e.g. previous due time), in UTC."""
    if after_instant_utc.tzinfo is None:
        after_instant_utc = after_instant_utc.replace(tzinfo=UTC)
    local = after_instant_utc.astimezone(tz)
    itr = croniter(cron_expression, local)
    next_local = itr.get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=tz)
    else:
        next_local = next_local.astimezone(tz)
    return next_local.astimezone(UTC)


def claim_lease_reclaimable(now_utc: datetime):
    """True when no active lease or the previous lease expired (crash / stalled worker recovery)."""
    return or_(
        ScheduledOperation.claim_expires_at.is_(None),
        ScheduledOperation.claim_expires_at < now_utc,
    )


def count_due_schedules(db: Session, *, now_utc: datetime) -> int:
    """Enabled schedules that are due for automatic execution and can be claimed (reclaimable lease)."""
    cron_due = and_(
        ScheduledOperation.next_run_at.is_not(None),
        ScheduledOperation.next_run_at <= now_utc,
    )
    retry_due = and_(
        ScheduledOperation.next_retry_at.is_not(None),
        ScheduledOperation.next_retry_at <= now_utc,
    )
    return (
        db.scalar(
            select(func.count())
            .select_from(ScheduledOperation)
            .where(
                and_(
                    ScheduledOperation.enabled.is_(True),
                    or_(cron_due, retry_due),
                    claim_lease_reclaimable(now_utc),
                )
            )
        )
        or 0
    )


def count_schedules_with_active_lease(db: Session, *, now_utc: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ScheduledOperation)
            .where(
                and_(
                    ScheduledOperation.claim_expires_at.is_not(None),
                    ScheduledOperation.claim_expires_at >= now_utc,
                )
            )
        )
        or 0
    )


def count_stale_claimed_leases(db: Session, *, now_utc: datetime) -> int:
    """Rows that still record a claim owner after lease expiry (typical crash mid-run). Reclaimable on next poll."""
    return (
        db.scalar(
            select(func.count())
            .select_from(ScheduledOperation)
            .where(
                and_(
                    ScheduledOperation.claim_owner_id.is_not(None),
                    ScheduledOperation.claim_expires_at.is_not(None),
                    ScheduledOperation.claim_expires_at < now_utc,
                )
            )
        )
        or 0
    )


def count_all_schedules(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ScheduledOperation)) or 0
