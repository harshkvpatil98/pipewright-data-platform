from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_workflows.backfill import (
    MAX_SLOTS,
    BackfillError,
    plan_backfill,
    queue_backfill,
)
from service_workflows.models import Workflow
from service_workflows.queue import claim_next_run
from shared_python.db import Base


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


@pytest.fixture()
def workflow(db: Session) -> Workflow:
    row = Workflow(
        project_id=uuid.uuid4(),
        name="nightly",
        trigger_type="cron",
        cron_expression="0 6 * * *",
        enabled=True,
        created_by_user_id=uuid.uuid4(),
        default_parameters={"region": "eu"},
    )
    db.add(row)
    db.commit()
    return row


def day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# -------------------------------------------------------------------- planning


def test_daily_range_produces_one_slot_per_day() -> None:
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-08"), interval="daily")
    assert plan.count == 7
    assert plan.slots[0] == day("2026-03-01")
    assert plan.slots[-1] == day("2026-03-07")


def test_the_end_is_exclusive() -> None:
    """'1st through 8th' is seven daily slots, not eight."""
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-08"))
    assert day("2026-03-08") not in plan.slots


def test_hourly_interval() -> None:
    plan = plan_backfill(
        start=day("2026-03-01T00:00"), end=day("2026-03-01T06:00"), interval="hourly"
    )
    assert plan.count == 6


def test_weekly_interval() -> None:
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-29"), interval="weekly")
    assert plan.count == 4


def test_monthly_interval_steps_by_month() -> None:
    plan = plan_backfill(start=day("2026-01-15"), end=day("2026-04-15"), interval="monthly")
    assert [slot.strftime("%Y-%m-%d") for slot in plan.slots] == [
        "2026-01-15",
        "2026-02-15",
        "2026-03-15",
    ]


def test_monthly_clamps_to_the_shortest_month() -> None:
    """31 January must land on the last day of February, not overflow."""
    plan = plan_backfill(start=day("2026-01-31"), end=day("2026-04-01"), interval="monthly")
    assert plan.slots[1].strftime("%Y-%m-%d") == "2026-02-28"


def test_monthly_crosses_a_year_boundary() -> None:
    plan = plan_backfill(start=day("2026-11-01"), end=day("2027-02-01"), interval="monthly")
    assert [slot.strftime("%Y-%m") for slot in plan.slots] == ["2026-11", "2026-12", "2027-01"]


def test_backwards_range_is_rejected() -> None:
    with pytest.raises(BackfillError, match="after its start"):
        plan_backfill(start=day("2026-03-08"), end=day("2026-03-01"))


def test_equal_bounds_are_rejected() -> None:
    with pytest.raises(BackfillError, match="after its start"):
        plan_backfill(start=day("2026-03-01"), end=day("2026-03-01"))


def test_unknown_interval_is_rejected() -> None:
    with pytest.raises(BackfillError, match="Interval must be"):
        plan_backfill(start=day("2026-03-01"), end=day("2026-03-02"), interval="fortnightly")


def test_an_enormous_range_is_refused_with_guidance() -> None:
    with pytest.raises(BackfillError, match="Narrow the range"):
        plan_backfill(start=day("2020-01-01"), end=day("2030-01-01"), interval="daily")


def test_the_cap_allows_a_range_just_under_it() -> None:
    plan = plan_backfill(
        start=day("2026-01-01T00:00"), end=day("2026-01-11T00:00"), interval="hourly"
    )
    assert plan.count == 240
    assert plan.count <= MAX_SLOTS


def test_naive_datetimes_are_treated_as_utc() -> None:
    plan = plan_backfill(
        start=datetime(2026, 3, 1), end=datetime(2026, 3, 3), interval="daily"
    )
    assert plan.count == 2


# -------------------------------------------------------------------- queueing


def test_each_slot_becomes_its_own_run(db: Session, workflow: Workflow) -> None:
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-04"))
    runs = queue_backfill(db, workflow=workflow, plan=plan, triggered_by_user_id=None)

    assert len(runs) == 3
    assert {run.status for run in runs} == {"queued"}
    assert {run.trigger for run in runs} == {"backfill"}


def test_each_run_carries_its_own_slot(db: Session, workflow: Workflow) -> None:
    """This is what makes macros resolve per-slot rather than all to today."""
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-04"))
    runs = queue_backfill(db, workflow=workflow, plan=plan, triggered_by_user_id=None)

    slots = sorted(run.logical_date.strftime("%Y-%m-%d") for run in runs)
    assert slots == ["2026-03-01", "2026-03-02", "2026-03-03"]


def test_backfill_runs_are_claimed_oldest_slot_first(db: Session, workflow: Workflow) -> None:
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-04"))
    queue_backfill(db, workflow=workflow, plan=plan, triggered_by_user_id=None)

    first = claim_next_run(db)
    assert first is not None
    assert first.logical_date.strftime("%Y-%m-%d") == "2026-03-01"


def test_workflow_defaults_are_merged_into_every_run(db: Session, workflow: Workflow) -> None:
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-03"))
    runs = queue_backfill(
        db, workflow=workflow, plan=plan, triggered_by_user_id=None, parameters={"mode": "repair"}
    )

    for run in runs:
        assert run.parameters_json["region"] == "eu"
        assert run.parameters_json["mode"] == "repair"
        assert run.parameters_json["backfill_interval"] == "daily"


def test_a_disabled_workflow_cannot_be_backfilled(db: Session, workflow: Workflow) -> None:
    workflow.enabled = False
    db.commit()
    plan = plan_backfill(start=day("2026-03-01"), end=day("2026-03-03"))

    with pytest.raises(BackfillError, match="disabled"):
        queue_backfill(db, workflow=workflow, plan=plan, triggered_by_user_id=None)
