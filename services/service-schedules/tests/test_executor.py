from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from service_schedules.execution import ScheduleExecutionOutcome
from service_schedules.models import ScheduledOperation
from service_schedules.scheduler_executor import claim_next_due_schedule, run_due_schedules_once
from service_pipeline_runs.schemas import PipelineRunRead
from service_auth.schemas import UserRead


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_disabled_schedule_not_claimed() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    assert (
        claim_next_due_schedule(db, now_utc=datetime.now(UTC), settings=SimpleNamespace(scheduler_runtime_id="a"))
        is None
    )


@patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome")
@patch("service_schedules.scheduler_executor.count_due_schedules", return_value=1)
@patch("service_schedules.scheduler_executor.count_all_schedules", return_value=2)
@patch("service_schedules.scheduler_executor.resolve_actor_user_for_schedule")
@patch("service_schedules.scheduler_executor.execute_schedule_operation")
@patch("service_schedules.scheduler_executor.claim_next_due_schedule")
def test_run_due_executes_once_per_claim(
    mock_claim, mock_exec, mock_resolve, mock_ca, mock_cd, _mock_notify
) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()

    row = MagicMock(spec=ScheduledOperation)
    row.id = sid
    row.project_id = pid
    row.schedule_type = "transformation_pipeline_run"
    row.target_config_json = {"pipeline_id": str(uuid.uuid4())}
    row.cron_expression = "0 * * * *"
    row.timezone = None

    due = datetime.now(UTC)
    mock_claim.side_effect = [(row, False, due), None]
    mock_resolve.return_value = _user()
    u = _user()
    run_read = PipelineRunRead(
        id=uuid.uuid4(),
        project_id=pid,
        triggered_by_user_id=u.id,
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
    mock_exec.return_value = ScheduleExecutionOutcome(
        success=True,
        message="ok",
        triggered_run=run_read,
        transformation=None,
        postgres_publish=None,
    )

    db = MagicMock()
    db.get.return_value = row

    summary = run_due_schedules_once(
        db, storage_backend=object(), settings=SimpleNamespace(scheduler_runtime_id="t")
    )

    assert summary.checked_count == 2
    assert summary.due_count == 1
    assert summary.triggered_count == 1
    assert summary.success_count == 1
    assert summary.failure_count == 0
    assert sid in summary.affected_schedule_ids
    mock_exec.assert_called_once()


@patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome")
@patch("service_schedules.scheduler_executor.count_due_schedules", return_value=1)
@patch("service_schedules.scheduler_executor.count_all_schedules", return_value=1)
@patch("service_schedules.scheduler_executor.resolve_actor_user_for_schedule")
@patch("service_schedules.scheduler_executor.execute_schedule_operation")
@patch("service_schedules.scheduler_executor.claim_next_due_schedule")
def test_run_due_failure_updates_metadata(
    mock_claim, mock_exec, mock_resolve, mock_ca, mock_cd, _mock_notify
) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    row = MagicMock(spec=ScheduledOperation)
    row.id = sid
    row.project_id = pid
    row.schedule_type = "transformation_pipeline_run"
    row.target_config_json = {"pipeline_id": str(uuid.uuid4())}
    row.cron_expression = "0 * * * *"
    row.timezone = None
    row.execution_count = 0
    row.max_retries = 1
    row.retry_count_current = 0
    row.name = "n"

    due = datetime.now(UTC)
    mock_claim.side_effect = [(row, False, due), None]
    mock_resolve.return_value = _user()
    mock_exec.side_effect = RuntimeError("boom")

    db = MagicMock()
    db.get.return_value = row

    summary = run_due_schedules_once(
        db, storage_backend=object(), settings=SimpleNamespace(scheduler_runtime_id="t")
    )
    assert summary.failure_count == 1
    assert summary.success_count == 0
    assert db.commit.call_count >= 1
