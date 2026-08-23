"""Backfills: replay a workflow across a range of past dates.

Each slot in the range becomes its own queued run carrying that slot as its
logical date, so date macros inside node configuration resolve to the slot being
reprocessed rather than to today. Reprocessing last March produces exactly what
last March would have produced.

Runs are queued, not executed here -- they join the same queue as manual and
scheduled runs, so one worker path handles everything and a large backfill
cannot monopolise the API.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from service_workflows.models import Workflow, WorkflowRun
from shared_python.errors import BadRequestError
from shared_python.logging import get_logger

logger = get_logger(__name__)

INTERVALS: tuple[str, ...] = ("hourly", "daily", "weekly", "monthly")

# A backfill is a bulk action; this bounds an accidental decade-wide request.
MAX_SLOTS = 500


@dataclass(frozen=True)
class BackfillPlan:
    slots: list[datetime]
    interval: str

    @property
    def count(self) -> int:
        return len(self.slots)


def _add_interval(moment: datetime, interval: str) -> datetime:
    if interval == "hourly":
        return moment + timedelta(hours=1)
    if interval == "daily":
        return moment + timedelta(days=1)
    if interval == "weekly":
        return moment + timedelta(weeks=1)

    # Monthly: step to the same day next month, clamping for short months so
    # 31 January advances to 28/29 February rather than overflowing.
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    day = min(moment.day, _days_in_month(year, month))
    return moment.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        following = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        following = datetime(year, month + 1, 1, tzinfo=UTC)
    return (following - timedelta(days=1)).day


def plan_backfill(
    *,
    start: datetime,
    end: datetime,
    interval: str = "daily",
) -> BackfillPlan:
    """Enumerate the slots a backfill would cover.

    The range is inclusive of `start` and exclusive of `end`, matching how a
    scheduled window is normally described ("1 March through 8 March" being
    seven daily slots, not eight).
    """
    if interval not in INTERVALS:
        raise BackfillError(
            f"Interval must be one of: {', '.join(INTERVALS)}."
        )

    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    if end <= start:
        raise BackfillError("The end of a backfill must be after its start.")

    slots: list[datetime] = []
    cursor = start
    while cursor < end:
        slots.append(cursor)
        if len(slots) > MAX_SLOTS:
            raise BackfillError(
                f"That range covers more than {MAX_SLOTS} {interval} slots. "
                "Narrow the range or use a coarser interval."
            )
        following = _add_interval(cursor, interval)
        if following <= cursor:  # pragma: no cover - defensive
            raise BackfillError("Interval did not advance; refusing to loop.")
        cursor = following

    return BackfillPlan(slots=slots, interval=interval)


class BackfillError(BadRequestError):
    """A backfill request that cannot be honoured."""


def queue_backfill(
    db: Session,
    *,
    workflow: Workflow,
    plan: BackfillPlan,
    triggered_by_user_id: uuid.UUID | None,
    parameters: dict[str, Any] | None = None,
) -> list[WorkflowRun]:
    """Queue one run per slot, oldest first."""
    if not workflow.enabled:
        raise BackfillError("This workflow is disabled.")
    if not plan.slots:
        raise BackfillError("That range contains no slots to run.")

    merged = {**(workflow.default_parameters or {}), **(parameters or {})}
    queued_at = datetime.now(UTC)
    runs: list[WorkflowRun] = []

    for index, slot in enumerate(plan.slots):
        run = WorkflowRun(
            workflow_id=workflow.id,
            project_id=workflow.project_id,
            status="queued",
            trigger="backfill",
            parameters_json={**merged, "backfill_interval": plan.interval} or None,
            logical_date=slot,
            # Ordering by queued_at is what the claim query uses, so nudging each
            # slot forward keeps a backfill running oldest-slot-first.
            queued_at=queued_at + timedelta(microseconds=index),
            triggered_by_user_id=triggered_by_user_id,
        )
        db.add(run)
        runs.append(run)

    db.commit()
    for run in runs:
        db.refresh(run)

    logger.info(
        "workflow_backfill_queued workflow_id=%s slots=%s interval=%s",
        workflow.id,
        len(runs),
        plan.interval,
    )
    return runs
