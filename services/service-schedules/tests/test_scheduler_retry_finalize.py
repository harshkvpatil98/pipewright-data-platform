from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from service_schedules.execution import ScheduleExecutionOutcome
from service_schedules.scheduler_executor import _finalize_after_automated_attempt
from service_pipeline_runs.schemas import PipelineRunRead


def _run_read(pid: uuid.UUID, uid: uuid.UUID) -> PipelineRunRead:
    return PipelineRunRead(
        id=uuid.uuid4(),
        project_id=pid,
        triggered_by_user_id=uid,
        pipeline_id=uuid.uuid4(),
        triggered_by_username=None,
        run_type="dataset_transformation",
        status="succeeded",
        started_at=None,
        completed_at=None,
        summary_json=None,
        logs_json=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome")
def test_finalize_automatic_failure_sets_retry_metadata(mock_notify: MagicMock) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    row = MagicMock()
    row.id = sid
    row.project_id = pid
    row.name = "Customer Cleanup"
    row.schedule_type = "transformation_pipeline_run"
    row.retry_count_current = 0
    row.max_retries = 1
    row.next_retry_at = None
    row.cron_expression = "0 * * * *"
    row.timezone = None
    row.claim_owner_id = "gw-1"

    db = MagicMock()
    db.get.return_value = row

    due = datetime.now(UTC)
    _finalize_after_automated_attempt(
        db,
        schedule_id=sid,
        outcome=None,
        exc=RuntimeError("boom"),
        is_retry_execution=False,
        cron_due_instant_utc=due,
        actor_user_id=uid,
    )

    assert row.claim_owner_id is None
    assert row.retry_count_current == 1
    assert row.next_retry_at is not None
    assert row.last_run_status == "failed"
    mock_notify.assert_called_once()


@patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome")
def test_finalize_automatic_success_resets_retry(mock_notify: MagicMock) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    row = MagicMock()
    row.id = sid
    row.project_id = pid
    row.name = "Customer Cleanup"
    row.schedule_type = "transformation_pipeline_run"
    row.retry_count_current = 1
    row.max_retries = 1
    row.next_retry_at = datetime.now(UTC)
    row.claim_owner_id = "gw-1"

    db = MagicMock()
    db.get.return_value = row
    outcome = ScheduleExecutionOutcome(
        success=True,
        message="ok",
        triggered_run=_run_read(pid, uid),
        transformation=None,
        postgres_publish=None,
    )

    _finalize_after_automated_attempt(
        db,
        schedule_id=sid,
        outcome=outcome,
        exc=None,
        is_retry_execution=True,
        cron_due_instant_utc=None,
        actor_user_id=uid,
    )

    assert row.retry_count_current == 0
    assert row.next_retry_at is None
    assert row.last_run_status == "succeeded"
    assert row.claim_owner_id is None
    mock_notify.assert_called_once()


@patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome")
def test_finalize_exhausted_retries_clears_next_retry(mock_notify: MagicMock) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    row = MagicMock()
    row.id = sid
    row.project_id = pid
    row.name = "Job"
    row.schedule_type = "postgres_publish"
    row.retry_count_current = 1
    row.max_retries = 1
    row.claim_owner_id = "x"

    db = MagicMock()
    db.get.return_value = row

    _finalize_after_automated_attempt(
        db,
        schedule_id=sid,
        outcome=None,
        exc=RuntimeError("still bad"),
        is_retry_execution=True,
        cron_due_instant_utc=None,
        actor_user_id=uid,
    )

    assert row.claim_owner_id is None
    assert row.next_retry_at is None
    assert row.retry_count_current == 1
    mock_notify.assert_called_once()


def test_count_due_includes_retry_window() -> None:
    from service_schedules.due import count_due_schedules

    db = MagicMock()
    db.scalar.return_value = 3
    n = count_due_schedules(db, now_utc=datetime.now(UTC))
    assert n == 3
    db.scalar.assert_called_once()
