from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from service_auth.schemas import UserRead
from service_schedules.execution import ScheduleExecutionOutcome
from service_schedules.models import ScheduledOperation
from service_schedules.scheduler_executor import claim_next_due_schedule, run_due_schedules_once
from service_schedules.service import _finalize_manual_trigger
from service_pipeline_runs.schemas import PipelineRunRead


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _due_row(*, retry: bool = False) -> MagicMock:
    now = datetime.now(UTC)
    row = MagicMock(spec=ScheduledOperation)
    row.enabled = True
    row.next_run_at = now - timedelta(minutes=5)
    row.next_retry_at = (now - timedelta(minutes=1)) if retry else None
    row.cron_expression = "0 * * * *"
    row.timezone = None
    row.claim_owner_id = None
    row.claim_acquired_at = None
    row.claim_expires_at = None
    return row


def test_claim_sets_lease_and_preserves_cron_due_for_finalize() -> None:
    now = datetime.now(UTC)
    row = _due_row()
    due_before = row.next_run_at
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    settings = SimpleNamespace(scheduler_runtime_id="replica-7", scheduler_claim_ttl_seconds=90)

    out = claim_next_due_schedule(db, now_utc=now, settings=settings)
    assert out is not None
    _, is_retry, cron_due = out
    assert is_retry is False
    assert cron_due == due_before
    assert row.claim_owner_id == "replica-7"
    assert row.claim_acquired_at == now
    assert row.claim_expires_at == now + timedelta(seconds=90)
    assert row.last_run_status == "running"
    db.commit.assert_called_once()


def test_claim_retry_clears_next_retry_at() -> None:
    now = datetime.now(UTC)
    row = _due_row(retry=True)
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    out = claim_next_due_schedule(
        db, now_utc=now, settings=SimpleNamespace(scheduler_runtime_id="a", scheduler_claim_ttl_seconds=60)
    )
    assert out is not None
    _, is_retry, cron_due = out
    assert is_retry is True
    assert cron_due is None
    assert row.next_retry_at is None
    db.commit.assert_called_once()


def test_second_claim_skips_while_lease_active() -> None:
    now = datetime.now(UTC)
    row = _due_row()

    def scalars(_stmt):
        m = MagicMock()
        reclaimable = row.claim_expires_at is None or row.claim_expires_at < now
        if row.enabled and row.next_run_at <= now and reclaimable:
            m.first.return_value = row
        else:
            m.first.return_value = None
        return m

    db = MagicMock()
    db.scalars.side_effect = scalars
    settings = SimpleNamespace(scheduler_runtime_id="w1", scheduler_claim_ttl_seconds=120)

    first = claim_next_due_schedule(db, now_utc=now, settings=settings)
    assert first is not None
    second = claim_next_due_schedule(db, now_utc=now, settings=settings)
    assert second is None


def test_expired_lease_can_be_reclaimed() -> None:
    now = datetime.now(UTC)
    row = _due_row()
    row.claim_owner_id = "crashed-worker"
    row.claim_acquired_at = now - timedelta(hours=1)
    row.claim_expires_at = now - timedelta(seconds=1)

    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    out = claim_next_due_schedule(
        db, now_utc=now, settings=SimpleNamespace(scheduler_runtime_id="w2", scheduler_claim_ttl_seconds=30)
    )
    assert out is not None
    assert row.claim_owner_id == "w2"


def test_run_due_preserves_retry_after_claim_flow() -> None:
    """Failure path still increments retry_count via finalize (claim does not change retry logic)."""
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
    row.max_retries = 2
    row.retry_count_current = 0
    row.name = "n"

    with (
        patch("service_schedules.scheduler_executor.notify_automated_schedule_outcome"),
        patch("service_schedules.scheduler_executor.count_due_schedules", return_value=1),
        patch("service_schedules.scheduler_executor.count_all_schedules", return_value=1),
        patch("service_schedules.scheduler_executor.resolve_actor_user_for_schedule") as mock_resolve,
        patch("service_schedules.scheduler_executor.execute_schedule_operation") as mock_exec,
        patch("service_schedules.scheduler_executor.claim_next_due_schedule") as mock_claim,
    ):
        mock_claim.side_effect = [(row, True, None), None]
        mock_resolve.return_value = _user()
        mock_exec.return_value = ScheduleExecutionOutcome(
            success=False,
            message="bad",
            triggered_run=None,
            transformation=None,
            postgres_publish=None,
        )
        db = MagicMock()
        db.get.return_value = row
        summary = run_due_schedules_once(
            db, storage_backend=object(), settings=SimpleNamespace(scheduler_runtime_id="t")
        )
        assert summary.failure_count == 1
        assert row.retry_count_current == 1
        assert row.next_retry_at is not None


def test_manual_finalize_clears_stale_claim_fields() -> None:
    sid = uuid.uuid4()
    row = MagicMock()
    row.claim_owner_id = "old"
    row.claim_acquired_at = datetime.now(UTC)
    row.claim_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    db = MagicMock()
    db.get.return_value = row
    outcome = ScheduleExecutionOutcome(
        success=True,
        message="ok",
        triggered_run=PipelineRunRead(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            triggered_by_user_id=uuid.uuid4(),
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
        ),
        transformation=None,
        postgres_publish=None,
    )
    _finalize_manual_trigger(db, sid, outcome)
    assert row.claim_owner_id is None
    assert row.claim_acquired_at is None
    assert row.claim_expires_at is None


def test_unset_runtime_id_uses_placeholder_owner() -> None:
    now = datetime.now(UTC)
    row = _due_row()
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    claim_next_due_schedule(db, now_utc=now, settings=SimpleNamespace(scheduler_runtime_id=None))
    assert row.claim_owner_id == "unset-runtime"
