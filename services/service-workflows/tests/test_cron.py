from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_workflows.cron import (
    advance_after_fire,
    apply_schedule,
    compute_next_run,
    due_workflows,
    validate_cron_expression,
)
from service_workflows.models import Workflow
from service_workflows.queue import enqueue_due_workflows
from shared_python.db import Base
from shared_python.errors import BadRequestError


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; Postgres keeps it."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def make_workflow(
    db: Session,
    *,
    trigger: str = "cron",
    cron: str | None = "0 6 * * *",
    timezone: str | None = "UTC",
    enabled: bool = True,
) -> Workflow:
    workflow = Workflow(
        project_id=uuid.uuid4(),
        name="scheduled",
        trigger_type=trigger,
        cron_expression=cron,
        timezone=timezone,
        enabled=enabled,
        created_by_user_id=uuid.uuid4(),
    )
    db.add(workflow)
    db.commit()
    return workflow


# ----------------------------------------------------------------- validation


@pytest.mark.parametrize("expression", ["0 6 * * *", "*/15 * * * *", "0 0 1 * *", "30 3 * * 1-5"])
def test_valid_expressions_are_accepted(expression: str) -> None:
    assert validate_cron_expression(expression) == expression


def test_whitespace_is_normalised() -> None:
    assert validate_cron_expression("  0   6  * * *  ") == "0 6 * * *"


@pytest.mark.parametrize("expression", ["", "   ", "not a cron", "99 99 * * *", "* * *"])
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(BadRequestError):
        validate_cron_expression(expression)


def test_rejection_message_shows_an_example() -> None:
    with pytest.raises(BadRequestError, match="0 6 \\* \\* \\*"):
        validate_cron_expression("every morning")


# -------------------------------------------------------------------- timing


def test_next_run_is_in_the_future() -> None:
    assert compute_next_run("*/5 * * * *", "UTC") > datetime.now(UTC)


def test_timezone_changes_the_utc_instant() -> None:
    """06:00 in Tokyo is a different moment than 06:00 in New York."""
    after = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    tokyo = compute_next_run("0 6 * * *", "Asia/Tokyo", after=after)
    new_york = compute_next_run("0 6 * * *", "America/New_York", after=after)
    assert tokyo != new_york


def test_unknown_timezone_falls_back_to_utc() -> None:
    after = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    assert compute_next_run("0 6 * * *", "Mars/Olympus", after=after) == compute_next_run(
        "0 6 * * *", "UTC", after=after
    )


# ------------------------------------------------------- applying a schedule


def test_cron_workflow_gets_a_next_run(db: Session) -> None:
    workflow = make_workflow(db)
    apply_schedule(workflow)
    assert workflow.next_run_at is not None


def test_manual_workflow_has_no_next_run(db: Session) -> None:
    workflow = make_workflow(db, trigger="manual", cron=None)
    apply_schedule(workflow)
    assert workflow.next_run_at is None


def test_disabling_clears_the_schedule(db: Session) -> None:
    """A disabled workflow must stop firing, not just fail when it does."""
    workflow = make_workflow(db)
    apply_schedule(workflow)
    assert workflow.next_run_at is not None

    workflow.enabled = False
    apply_schedule(workflow)
    assert workflow.next_run_at is None


def test_switching_to_cron_requires_a_valid_expression(db: Session) -> None:
    workflow = make_workflow(db, cron="nonsense")
    with pytest.raises(BadRequestError):
        apply_schedule(workflow)


# ------------------------------------------------------------ due detection


def test_workflow_is_due_once_its_time_passes(db: Session) -> None:
    workflow = make_workflow(db)
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert [item.id for item in due_workflows(db)] == [workflow.id]


def test_future_schedule_is_not_due(db: Session) -> None:
    workflow = make_workflow(db)
    workflow.next_run_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()
    assert due_workflows(db) == []


def test_disabled_workflow_is_never_due(db: Session) -> None:
    workflow = make_workflow(db, enabled=False)
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert due_workflows(db) == []


def test_manual_workflow_is_never_due(db: Session) -> None:
    workflow = make_workflow(db, trigger="manual", cron=None)
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert due_workflows(db) == []


# ------------------------------------------------------------- advancing on


def test_firing_advances_to_the_next_slot(db: Session) -> None:
    workflow = make_workflow(db, cron="0 6 * * *")
    workflow.next_run_at = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 6, 0, 5, tzinfo=UTC)

    advance_after_fire(workflow, now=now)

    assert workflow.next_run_at == datetime(2026, 6, 2, 6, 0, tzinfo=UTC)


def test_a_long_outage_skips_missed_slots_rather_than_replaying_them(db: Session) -> None:
    """Catching up would fire a daily job dozens of times; backfills exist for that."""
    workflow = make_workflow(db, cron="0 6 * * *")
    workflow.next_run_at = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    now = datetime(2026, 6, 10, 7, 0, tzinfo=UTC)

    advance_after_fire(workflow, now=now)

    assert workflow.next_run_at == datetime(2026, 6, 11, 6, 0, tzinfo=UTC)


def test_advancing_a_manual_workflow_clears_the_schedule(db: Session) -> None:
    workflow = make_workflow(db, trigger="manual", cron=None)
    workflow.next_run_at = datetime.now(UTC)
    advance_after_fire(workflow)
    assert workflow.next_run_at is None


# ------------------------------------------------------------- enqueueing


def test_due_workflow_is_queued_and_rescheduled(db: Session) -> None:
    workflow = make_workflow(db, cron="0 6 * * *")
    fired_at = datetime.now(UTC) - timedelta(minutes=1)
    workflow.next_run_at = fired_at
    db.commit()

    queued = enqueue_due_workflows(db)

    assert len(queued) == 1
    assert queued[0].trigger == "cron"
    assert queued[0].status == "queued"

    # The schedule moved forward, so this occurrence cannot fire again.
    db.refresh(workflow)
    assert _as_utc(workflow.next_run_at) > datetime.now(UTC)


def test_the_same_occurrence_is_not_queued_twice(db: Session) -> None:
    """A second tick before the next slot must not re-queue the same run."""
    workflow = make_workflow(db, cron="0 6 * * *")
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    first = enqueue_due_workflows(db)
    second = enqueue_due_workflows(db)

    assert len(first) == 1
    assert second == []


def test_queued_cron_run_records_the_scheduled_instant(db: Session) -> None:
    workflow = make_workflow(db, cron="0 6 * * *")
    scheduled = datetime.now(UTC) - timedelta(minutes=1)
    workflow.next_run_at = scheduled
    db.commit()

    run = enqueue_due_workflows(db)[0]
    assert "scheduled_for" in (run.parameters_json or {})


def test_cron_run_is_attributed_to_the_workflow_owner(db: Session) -> None:
    """A scheduled run has no requesting user, so it acts as the workflow's creator."""
    workflow = make_workflow(db)
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    run = enqueue_due_workflows(db)[0]
    assert run.triggered_by_user_id == workflow.created_by_user_id


def test_nothing_due_queues_nothing(db: Session) -> None:
    make_workflow(db)
    assert enqueue_due_workflows(db) == []
