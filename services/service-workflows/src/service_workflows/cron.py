"""Cron scheduling for workflows.

Reuses the scheduler's cron helpers so both features interpret an expression and
a timezone identically -- one behaviour to reason about, and DST is handled in a
single place.
"""

from __future__ import annotations

from datetime import UTC, datetime

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_schedules.due import (
    compute_first_next_run_utc,
    compute_next_run_after_utc,
    resolve_schedule_timezone,
)
from service_workflows.models import Workflow
from shared_python.errors import BadRequestError
from shared_python.logging import get_logger

logger = get_logger(__name__)

MAX_CRON_LENGTH = 120


def validate_cron_expression(expression: str) -> str:
    """Return a cleaned cron expression, or explain why it is not usable."""
    if not isinstance(expression, str) or not expression.strip():
        raise BadRequestError("A cron expression is required for a scheduled workflow.")

    cleaned = " ".join(expression.strip().split())
    if len(cleaned) > MAX_CRON_LENGTH:
        raise BadRequestError(f"Cron expression is too long (limit {MAX_CRON_LENGTH} characters).")

    try:
        croniter(cleaned, datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001 - croniter raises several types
        raise BadRequestError(
            f"'{cleaned}' is not a valid cron expression. Use five fields, "
            "for example '0 6 * * *' for 06:00 daily."
        ) from exc

    return cleaned


def compute_next_run(
    cron_expression: str, timezone_name: str | None, *, after: datetime | None = None
) -> datetime:
    """Next occurrence strictly after `after` (default now), returned in UTC."""
    tz = resolve_schedule_timezone(timezone_name)
    if after is None:
        return compute_first_next_run_utc(cron_expression, tz)
    return compute_next_run_after_utc(cron_expression, tz, after)


def apply_schedule(workflow: Workflow, *, now: datetime | None = None) -> None:
    """Keep a workflow's `next_run_at` consistent with its trigger settings.

    Called whenever the trigger changes, so a workflow switched to manual stops
    firing and one switched to cron starts from the next occurrence rather than
    immediately.
    """
    if workflow.trigger_type != "cron" or not workflow.enabled:
        workflow.next_run_at = None
        return

    expression = validate_cron_expression(workflow.cron_expression or "")
    workflow.cron_expression = expression
    workflow.next_run_at = compute_next_run(expression, workflow.timezone, after=now)


def due_workflows(db: Session, *, now: datetime | None = None) -> list[Workflow]:
    """Enabled cron workflows whose next occurrence has arrived."""
    moment = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(Workflow)
            .where(
                Workflow.enabled.is_(True),
                Workflow.trigger_type == "cron",
                Workflow.next_run_at.is_not(None),
                Workflow.next_run_at <= moment,
            )
            .order_by(Workflow.next_run_at.asc())
        ).all()
    )


def advance_after_fire(workflow: Workflow, *, now: datetime | None = None) -> None:
    """Move `next_run_at` to the following occurrence after a workflow fires.

    Advancing from the *scheduled* instant rather than from now keeps a schedule
    on its intended grid. If the worker was down long enough that the next slot
    is also in the past, the loop skips forward instead of firing repeatedly to
    catch up -- backfills are the deliberate way to reprocess missed windows.
    """
    moment = now or datetime.now(UTC)
    if workflow.trigger_type != "cron" or not workflow.cron_expression:
        workflow.next_run_at = None
        return

    anchor = workflow.next_run_at or moment
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    following = compute_next_run(workflow.cron_expression, workflow.timezone, after=anchor)
    skipped = 0
    while following <= moment:
        following = compute_next_run(workflow.cron_expression, workflow.timezone, after=following)
        skipped += 1
        # Guard against a pathological expression looping forever.
        if skipped > 10_000:
            following = compute_next_run(workflow.cron_expression, workflow.timezone, after=moment)
            break

    if skipped:
        logger.warning(
            "workflow_schedule_slots_skipped workflow_id=%s skipped=%s", workflow.id, skipped
        )
    workflow.next_run_at = following
