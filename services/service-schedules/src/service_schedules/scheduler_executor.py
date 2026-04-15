from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session

from service_notifications.outcomes import notify_automated_schedule_outcome
from service_schedules.due import (
    claim_lease_reclaimable,
    clear_schedule_execution_lease,
    compute_next_run_after_utc,
    count_all_schedules,
    count_due_schedules,
    resolve_schedule_timezone,
)
from service_schedules.execution import ScheduleExecutionOutcome, execute_schedule_operation
from service_schedules.models import ScheduledOperation
from service_schedules.retry_backoff import compute_next_retry_at
from service_schedules.runtime import resolve_actor_user_for_schedule
from service_schedules.schemas import RunDueSchedulesSummary


def _scheduler_runtime_owner(settings: Any | None) -> str:
    raw = getattr(settings, "scheduler_runtime_id", None) if settings is not None else None
    if raw is None:
        return ""
    return str(raw).strip()


def _claim_ttl_seconds(settings: Any | None) -> int:
    if settings is None:
        return 300
    v = getattr(settings, "scheduler_claim_ttl_seconds", 300)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 300
    return max(30, min(n, 86400))


def _clear_claim_fields(row: ScheduledOperation) -> None:
    row.claim_owner_id = None
    row.claim_acquired_at = None
    row.claim_expires_at = None


def claim_next_due_schedule(
    db: Session, *, now_utc: datetime, settings: Any | None = None
) -> tuple[ScheduledOperation, bool, datetime | None] | None:
    """
    Lease-claim one due schedule (automatic execution only).

    Returns (row, is_retry_execution, cron_due_instant_utc). The third value is the cron slot instant
    when this is a cron (non-retry) claim; finalize uses it to advance next_run_at after the attempt.
    Retries clear next_retry_at at claim time and leave next_run_at unchanged through finalize.
    """
    owner = _scheduler_runtime_owner(settings) or "unset-runtime"
    ttl = _claim_ttl_seconds(settings)
    expires = now_utc + timedelta(seconds=ttl)

    is_retry_due = and_(
        ScheduledOperation.next_retry_at.is_not(None),
        ScheduledOperation.next_retry_at <= now_utc,
    )
    is_cron_due = and_(
        ScheduledOperation.next_run_at.is_not(None),
        ScheduledOperation.next_run_at <= now_utc,
    )
    retry_priority = case((is_retry_due, 0), else_=1)
    due_ts = case((is_retry_due, ScheduledOperation.next_retry_at), else_=ScheduledOperation.next_run_at)
    stmt = (
        select(ScheduledOperation)
        .where(
            and_(
                ScheduledOperation.enabled.is_(True),
                or_(is_retry_due, is_cron_due),
                claim_lease_reclaimable(now_utc),
            )
        )
        .order_by(retry_priority.asc(), due_ts.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = db.scalars(stmt).first()
    if row is None:
        return None

    is_retry_execution = row.next_retry_at is not None and row.next_retry_at <= now_utc
    cron_due_instant: datetime | None = None
    if is_retry_execution:
        row.next_retry_at = None
    else:
        due_instant = row.next_run_at
        assert due_instant is not None
        if due_instant.tzinfo is None:
            due_instant = due_instant.replace(tzinfo=UTC)
        cron_due_instant = due_instant

    row.claim_owner_id = owner[:128]
    row.claim_acquired_at = now_utc
    row.claim_expires_at = expires
    row.last_run_started_at = now_utc
    row.last_run_status = "running"
    row.last_error_message = None
    db.commit()
    db.refresh(row)
    return row, is_retry_execution, cron_due_instant


def _finalize_after_automated_attempt(
    db: Session,
    *,
    schedule_id: uuid.UUID,
    outcome: ScheduleExecutionOutcome | None,
    exc: Exception | None,
    is_retry_execution: bool,
    cron_due_instant_utc: datetime | None,
    actor_user_id: uuid.UUID,
) -> None:
    row = db.get(ScheduledOperation, schedule_id)
    if row is None:
        return
    finished = datetime.now(UTC)
    row.last_run_finished_at = finished
    row.last_triggered_at = finished
    row.execution_count = int(row.execution_count or 0) + 1

    success = False
    detail_message: str | None = None
    if exc is not None:
        row.last_run_status = "failed"
        detail_message = str(exc)[:2000]
        row.last_error_message = detail_message
    elif outcome is not None:
        success = bool(outcome.success)
        row.last_run_status = "succeeded" if success else "failed"
        row.last_error_message = (
            None if success else (outcome.message[:2000] if outcome.message else None)
        )
        detail_message = row.last_error_message
    else:
        row.last_run_status = "failed"
        row.last_error_message = "No outcome recorded."
        detail_message = row.last_error_message

    triggered_run = outcome.triggered_run if outcome else None

    if success:
        row.retry_count_current = 0
        row.next_retry_at = None
    else:
        row.last_failure_at = finished
        max_r = int(row.max_retries or 0)
        current = int(row.retry_count_current or 0)
        if current < max_r:
            row.retry_count_current = current + 1
            row.next_retry_at = compute_next_retry_at(
                now_utc=finished, attempt_number=int(row.retry_count_current)
            )
        else:
            row.next_retry_at = None

    if not is_retry_execution and cron_due_instant_utc is not None:
        due_inst = cron_due_instant_utc
        if due_inst.tzinfo is None:
            due_inst = due_inst.replace(tzinfo=UTC)
        tz = resolve_schedule_timezone(row.timezone)
        row.next_run_at = compute_next_run_after_utc(row.cron_expression, tz, due_inst)

    clear_schedule_execution_lease(row)

    db.commit()
    db.refresh(row)

    notify_automated_schedule_outcome(
        db,
        user_id=actor_user_id,
        project_id=row.project_id,
        schedule_id=row.id,
        schedule_name=row.name,
        schedule_type=row.schedule_type,
        success=success,
        detail_message=detail_message,
        triggered_run=triggered_run,
        is_retry_execution=is_retry_execution,
    )


def run_due_schedules_once(
    db: Session,
    *,
    storage_backend: Any,
    settings: Any,
) -> RunDueSchedulesSummary:
    """Process due schedules until none remain due. Intended for cron or an internal poll loop."""
    now = datetime.now(UTC)
    checked_count = count_all_schedules(db)
    due_count = count_due_schedules(db, now_utc=now)
    triggered_count = 0
    success_count = 0
    failure_count = 0
    affected: list[uuid.UUID] = []

    while True:
        now = datetime.now(UTC)
        claimed = claim_next_due_schedule(db, now_utc=now, settings=settings)
        if claimed is None:
            break
        row, is_retry_execution, cron_due_instant = claimed
        sid = row.id
        triggered_count += 1
        affected.append(sid)
        outcome: ScheduleExecutionOutcome | None = None
        err: Exception | None = None
        user = resolve_actor_user_for_schedule(db, row)
        try:
            outcome = execute_schedule_operation(
                db,
                row=row,
                current_user=user,
                storage_backend=storage_backend,
                settings=settings,
                notify_on_complete=False,
            )
            if outcome.success:
                success_count += 1
            else:
                failure_count += 1
        except Exception as e:
            err = e
            failure_count += 1
        finally:
            _finalize_after_automated_attempt(
                db,
                schedule_id=sid,
                outcome=outcome,
                exc=err,
                is_retry_execution=is_retry_execution,
                cron_due_instant_utc=cron_due_instant,
                actor_user_id=user.id,
            )

    return RunDueSchedulesSummary(
        checked_count=checked_count,
        due_count=due_count,
        triggered_count=triggered_count,
        success_count=success_count,
        failure_count=failure_count,
        affected_schedule_ids=affected,
    )
