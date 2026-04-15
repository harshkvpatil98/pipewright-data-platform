from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import NotFoundError

from service_schedules.due import (
    clear_schedule_execution_lease,
    compute_first_next_run_utc,
    resolve_schedule_timezone,
)
from service_schedules.execution import ScheduleExecutionOutcome, execute_schedule_operation
from service_schedules.models import ScheduledOperation
from service_schedules.schemas import (
    ScheduledOperationCreate,
    ScheduledOperationListResponse,
    ScheduledOperationRead,
    ScheduledOperationUpdate,
    ScheduleTriggerResponse,
)
from service_schedules.validators import validate_and_normalize_target_config, validate_cron_expression


def _to_read(row: ScheduledOperation) -> ScheduledOperationRead:
    return ScheduledOperationRead.model_validate(row, from_attributes=True)


def sync_next_run_at_for_row(row: ScheduledOperation) -> None:
    """Set next_run_at from cron (or clear when disabled). Clears retry state when disabled."""
    if not row.enabled:
        row.next_run_at = None
        row.next_retry_at = None
        row.retry_count_current = 0
        return
    tz = resolve_schedule_timezone(row.timezone)
    row.next_run_at = compute_first_next_run_utc(row.cron_expression, tz)


def create_schedule(
    db: Session,
    *,
    project_id: uuid.UUID,
    payload: ScheduledOperationCreate,
    current_user: UserRead,
) -> ScheduledOperationRead:
    ensure_owned_project(db, project_id, current_user.id)
    cron_expression = validate_cron_expression(payload.cron_expression)
    normalized = validate_and_normalize_target_config(
        db,
        project_id=project_id,
        schedule_type=payload.schedule_type,
        target=payload.target_config,
    )
    row = ScheduledOperation(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        schedule_type=payload.schedule_type,
        cron_expression=cron_expression,
        timezone=payload.timezone.strip() if payload.timezone else None,
        enabled=payload.enabled,
        target_config_json=normalized,
        created_by_user_id=current_user.id,
        execution_count=0,
        retry_count_current=0,
        max_retries=1,
    )
    sync_next_run_at_for_row(row)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def list_schedules(db: Session, *, project_id: uuid.UUID, current_user: UserRead) -> ScheduledOperationListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(ScheduledOperation)
        .where(ScheduledOperation.project_id == project_id)
        .order_by(ScheduledOperation.created_at.desc())
    ).all()
    return ScheduledOperationListResponse(items=[_to_read(r) for r in rows])


def get_schedule(
    db: Session, *, project_id: uuid.UUID, schedule_id: uuid.UUID, current_user: UserRead
) -> ScheduledOperationRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.get(ScheduledOperation, schedule_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Schedule not found.")
    return _to_read(row)


def _get_schedule_model(
    db: Session, *, project_id: uuid.UUID, schedule_id: uuid.UUID, current_user: UserRead
) -> ScheduledOperation:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.get(ScheduledOperation, schedule_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Schedule not found.")
    return row


def update_schedule(
    db: Session,
    *,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: ScheduledOperationUpdate,
    current_user: UserRead,
) -> ScheduledOperationRead:
    row = _get_schedule_model(db, project_id=project_id, schedule_id=schedule_id, current_user=current_user)
    recompute_next = False
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.description is not None:
        row.description = payload.description.strip() if payload.description else None
    if payload.cron_expression is not None:
        row.cron_expression = validate_cron_expression(payload.cron_expression)
        recompute_next = True
    if payload.timezone is not None:
        row.timezone = payload.timezone.strip() if payload.timezone else None
        recompute_next = True
    if payload.enabled is not None:
        row.enabled = payload.enabled
        recompute_next = True
    if payload.target_config is not None:
        row.target_config_json = validate_and_normalize_target_config(
            db,
            project_id=project_id,
            schedule_type=row.schedule_type,  # type: ignore[arg-type]
            target=payload.target_config,
        )
    if recompute_next:
        row.next_retry_at = None
        row.retry_count_current = 0
        sync_next_run_at_for_row(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def toggle_schedule(
    db: Session,
    *,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    enabled: bool,
    current_user: UserRead,
) -> ScheduledOperationRead:
    row = _get_schedule_model(db, project_id=project_id, schedule_id=schedule_id, current_user=current_user)
    row.enabled = enabled
    sync_next_run_at_for_row(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def _finalize_manual_trigger(db: Session, schedule_id: uuid.UUID, outcome: ScheduleExecutionOutcome) -> None:
    row = db.get(ScheduledOperation, schedule_id)
    if row is None:
        return
    now = datetime.now(UTC)
    clear_schedule_execution_lease(row)
    row.last_triggered_at = now
    row.last_run_started_at = now
    row.last_run_finished_at = now
    row.last_run_status = "succeeded" if outcome.success else "failed"
    row.last_error_message = None if outcome.success else (outcome.message[:2000] if outcome.message else None)
    row.execution_count = int(row.execution_count or 0) + 1
    db.commit()


def trigger_schedule_now(
    db: Session,
    *,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
) -> ScheduleTriggerResponse:
    row = _get_schedule_model(db, project_id=project_id, schedule_id=schedule_id, current_user=current_user)
    outcome = execute_schedule_operation(
        db,
        row=row,
        current_user=current_user,
        storage_backend=storage_backend,
        settings=settings,
    )
    _finalize_manual_trigger(db, schedule_id, outcome)
    row_after = db.get(ScheduledOperation, schedule_id)
    if row_after is None:
        raise NotFoundError("Schedule not found.")

    return ScheduleTriggerResponse(
        success=outcome.success,
        message=outcome.message,
        schedule=_to_read(row_after),
        triggered_run=outcome.triggered_run,
        transformation=outcome.transformation,
        postgres_publish=outcome.postgres_publish,
    )


