"""Runs at once per project, what goes first, and a memory ceiling (D2, O8).

Ten runs in one project used to run all at once, first come first served,
with no ceiling on memory. Now a project has a limit (its own or the
deployment's, 4): a run a person starts beyond it is refused with the
reason, queued work waits while other projects' work goes ahead, a
person's runs go before scheduled ones and backfills, and a recipe whose
data outgrows the ceiling stops at the step that did it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from service_auth.models import User
from service_auth.schemas import UserRead
from service_pipeline_runs import background, limits
from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.service import create_pipeline_run, mark_pipeline_run_running
from service_projects.schemas import ProjectCreate, ProjectUpdate
from service_projects.service import create_project, update_project
from service_schedules.models import ScheduledOperation
from service_workflows.models import Workflow, WorkflowRun
from shared_python.db import Base
from shared_python.errors import BadRequestError, TooManyRequestsError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db: Session, monkeypatch) -> dict:
    monkeypatch.delenv("PROJECT_RUNS_AT_ONCE", raising=False)
    monkeypatch.delenv("WORKFLOW_MAX_RUNS_PER_PROJECT", raising=False)
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    busy = create_project(db, ProjectCreate(name="Busy", description=None), user)
    quiet = create_project(db, ProjectCreate(name="Quiet", description=None), user)
    return {"user": user, "busy": busy.id, "quiet": quiet.id}


def _running(db: Session, world: dict, project_id: uuid.UUID, count: int, origin: str = "person") -> None:
    for _ in range(count):
        db.add(PipelineRun(project_id=project_id, triggered_by_user_id=world["user"].id, run_type="dataset_transformation",
                           status="running", origin=origin))
    db.commit()


def _start(db: Session, world: dict, project_id: uuid.UUID) -> PipelineRun:
    run = create_pipeline_run(db, project_id=project_id, current_user=world["user"], run_type="dataset_transformation")
    return mark_pipeline_run_running(db, run=run)


def test_a_run_a_person_starts_beyond_the_limit_is_refused_with_the_reason(db: Session, world: dict) -> None:
    _running(db, world, world["busy"], 3)
    _start(db, world, world["busy"])  # the fourth fits
    db.commit()
    with pytest.raises(TooManyRequestsError, match="already has 4 runs going") as refused:
        _start(db, world, world["busy"])
    assert refused.value.retry_after > 0
    db.rollback()
    _start(db, world, world["quiet"])  # another project is not held up


def test_a_project_can_set_its_own_limit_and_go_back_to_the_deployment_s(db: Session, world: dict, monkeypatch) -> None:
    updated = update_project(db, world["busy"], ProjectUpdate(max_runs_at_once=1), world["user"])
    assert updated.max_runs_at_once == 1  # what the settings page shows
    _running(db, world, world["busy"], 1)
    with pytest.raises(TooManyRequestsError, match="1 run going"):
        _start(db, world, world["busy"])
    db.rollback()
    assert update_project(db, world["busy"], ProjectUpdate(max_runs_at_once=None), world["user"]).max_runs_at_once is None
    _start(db, world, world["busy"])
    db.commit()
    # The deployment's limit, by its new name or the one it had when it counted only workflow runs.
    monkeypatch.setenv("WORKFLOW_MAX_RUNS_PER_PROJECT", "2")
    assert limits.limit_for(db, world["quiet"]) == 2
    monkeypatch.setenv("PROJECT_RUNS_AT_ONCE", "6")
    assert limits.limit_for(db, world["quiet"]) == 6


def test_what_a_workflow_starts_is_part_of_it_and_never_refused(db: Session, world: dict) -> None:
    workflow = Workflow(project_id=world["busy"], name="Nightly")
    db.add(workflow)
    db.flush()
    db.add(WorkflowRun(workflow_id=workflow.id, project_id=world["busy"], status="running", trigger="cron",
                       queued_at=datetime.now(UTC)))
    _running(db, world, world["busy"], 3, origin="workflow")
    assert limits.going(db, world["busy"]) == 1  # the workflow run, not its three recipe runs
    _running(db, world, world["busy"], 3)
    with limits.started_by("workflow"):
        run = _start(db, world, world["busy"])  # the project is full, but this is part of a run already going
    assert run.origin == "workflow" and run.status == "running"


def test_queued_work_waits_and_a_person_s_goes_first(db: Session, world: dict) -> None:
    done: list[str] = []
    background.register("limits_test", lambda db, run, storage, settings: done.append(run.origin))
    base = datetime.now(UTC) - timedelta(minutes=30)
    # Ten runs queued in one project, oldest first: backfills, then scheduled, then a person's.
    for minutes, origin in enumerate(["backfill"] * 3 + ["schedule"] * 3 + ["person"] * 4):
        db.add(PipelineRun(project_id=world["busy"], triggered_by_user_id=world["user"].id, run_type="limits_test",
                           status="queued", origin=origin, request_json={}, created_at=base + timedelta(minutes=minutes)))
    db.add(PipelineRun(project_id=world["quiet"], triggered_by_user_id=world["user"].id, run_type="limits_test",
                       status="queued", origin="backfill", request_json={}, created_at=base + timedelta(hours=1)))
    db.commit()

    claimed = [background.claim_next(db, owner="w1") for _ in range(4)]
    assert [run.origin for run in claimed] == ["person"] * 4
    # Four going: the busy project waits, and the quiet one's backfill goes ahead of it.
    other = background.claim_next(db, owner="w1")
    assert other.project_id == world["quiet"]
    assert background.claim_next(db, owner="w1") is None
    claimed[0].status = "succeeded"
    db.commit()
    assert background.claim_next(db, owner="w1").origin == "schedule"


def test_a_due_schedule_in_a_full_project_waits_for_a_later_pass(db: Session, world: dict) -> None:
    from service_schedules.scheduler_executor import claim_next_due_schedule

    now = datetime.now(UTC)
    for project_id in (world["busy"], world["quiet"]):
        db.add(ScheduledOperation(project_id=project_id, name="Hourly", schedule_type="transformation_pipeline_run",
                                  cron_expression="0 * * * *", target_config_json={}, next_run_at=now - timedelta(minutes=5)))
    db.commit()
    _running(db, world, world["busy"], 4)
    row, _retry, _due = claim_next_due_schedule(db, now_utc=now)
    assert row.project_id == world["quiet"]
    assert claim_next_due_schedule(db, now_utc=now) is None  # still due, not skipped
    busy = db.scalar(select(ScheduledOperation).where(ScheduledOperation.project_id == world["busy"]))
    assert busy.next_run_at is not None and busy.claim_owner_id is None


def test_workflow_runs_a_person_started_go_before_scheduled_ones_and_backfills(db: Session, world: dict) -> None:
    from service_workflows.queue import claim_next_run

    workflow = Workflow(project_id=world["busy"], name="Loads")
    db.add(workflow)
    db.flush()
    base = datetime.now(UTC) - timedelta(minutes=10)
    for minutes, trigger in enumerate(["backfill", "cron", "manual"]):
        db.add(WorkflowRun(workflow_id=workflow.id, project_id=world["busy"], status="queued", trigger=trigger,
                           queued_at=base + timedelta(minutes=minutes)))
    db.commit()
    assert [claim_next_run(db).trigger for _ in range(3)] == ["manual", "cron", "backfill"]


def test_a_step_that_grows_the_data_past_the_ceiling_stops_the_run_there(monkeypatch) -> None:
    from service_transformations.executor import apply_transformation_steps_with_outcomes
    from shared_python import memory

    monkeypatch.setattr(memory, "SMALLEST_LIMIT_MB", 1)
    monkeypatch.setenv("RUN_MEMORY_LIMIT_MB", "2")
    # About 0.9 MB on macOS and Linux alike (object sizes differ a little between them), well
    # under the ceiling; the derived column of 160-character text takes it well over.
    frame = pd.DataFrame({"note": ["x" * 40] * 8_000, "n": range(8_000)})
    steps = [
        {"step_type": "filter_rows", "config": {"conditions": [{"column": "n", "operator": "greater_or_equal", "value": 0}]}},
        {"step_type": "derive_column", "config": {"target_column": "again",
                                                  "formula": "=CONCAT([note], [note], [note], [note])"}},
    ]
    with pytest.raises(BadRequestError, match=r"Step 2 \(derive column\) made the data 2\.[3-9] MB, past this run's ceiling of 2\.0 MB"):
        apply_transformation_steps_with_outcomes(frame, steps)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Address-space limits are enforced on Linux.")
def test_on_linux_the_worker_s_cap_turns_an_allocation_into_a_memory_error() -> None:
    script = (
        "from shared_python.memory import cap_address_space\n"
        "cap = cap_address_space(headroom_mb=512)\n"
        "import numpy\n"
        "try:\n"
        "    numpy.ones(cap // 8 + 1)\n"
        "except MemoryError:\n"
        "    print('memory error')\n"
    )
    env = {**os.environ, "RUN_MEMORY_LIMIT_MB": "256"}
    env.pop("WORKER_ADDRESS_SPACE_CAP", None)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert out.stdout.strip() == "memory error", out.stderr
