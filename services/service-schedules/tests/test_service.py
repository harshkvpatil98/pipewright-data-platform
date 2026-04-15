from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_destinations.publish_schemas import DatasetPublishPostgresResponse, DestinationPublishSummary
from service_datasets.schemas import DatasetDetailRead
from service_pipeline_runs.schemas import PipelineRunRead
from service_schedules.models import ScheduledOperation
from service_schedules.execution import ScheduleExecutionOutcome
from service_schedules.schemas import ScheduledOperationCreate
from service_schedules.service import create_schedule, toggle_schedule, trigger_schedule_now
from service_transformations.schemas import TransformationRunResponse
from shared_python.errors import NotFoundError


def _dataset_detail(pid: uuid.UUID) -> DatasetDetailRead:
    now = datetime.now(UTC)
    return DatasetDetailRead(
        id=uuid.uuid4(),
        project_id=pid,
        source_id=None,
        uploaded_by_user_id=None,
        pipeline_run_id=None,
        parent_dataset_id=None,
        created_from_pipeline_id=None,
        name="derived",
        original_filename="f.csv",
        file_name="f.csv",
        file_type="csv",
        file_size_bytes=10,
        is_derived=True,
        status="ready",
        ingestion_status="succeeded",
        row_count=1,
        column_count=1,
        created_at=now,
        updated_at=now,
        schema_snapshot=None,
        schema_json=None,
        profile_json=None,
        preview_json=None,
        ingestion_error=None,
        last_profiled_at=None,
    )


def _schedule_row(sid: uuid.UUID, pid: uuid.UUID, stype: str, cfg: dict, *, uid: uuid.UUID | None = None) -> MagicMock:
    row = MagicMock(spec=ScheduledOperation)
    row.id = sid
    row.project_id = pid
    row.name = "sched"
    row.description = None
    row.schedule_type = stype
    row.cron_expression = "0 9 * * *"
    row.timezone = None
    row.enabled = True
    row.target_config_json = cfg
    row.created_by_user_id = uid or uuid.uuid4()
    row.last_triggered_at = None
    row.next_run_at = None
    row.last_run_started_at = None
    row.last_run_finished_at = None
    row.last_run_status = None
    row.last_error_message = None
    row.execution_count = 0
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_schedules.service.ensure_owned_project", side_effect=NotFoundError("missing"))
def test_create_requires_owned_project(_e) -> None:
    db = MagicMock()
    with pytest.raises(NotFoundError):
        create_schedule(
            db,
            project_id=uuid.uuid4(),
            payload=ScheduledOperationCreate(
                name="s",
                schedule_type="transformation_pipeline_run",
                cron_expression="0 9 * * *",
                target_config={"pipeline_id": str(uuid.uuid4())},
            ),
            current_user=_user(),
        )


@patch("service_schedules.service.validate_and_normalize_target_config")
@patch("service_schedules.service.validate_cron_expression", return_value="0 9 * * *")
@patch("service_schedules.service.ensure_owned_project")
def test_create_persists(ensure_owned, _vcron, validate_target) -> None:
    ensure_owned.return_value = MagicMock()
    pid = uuid.uuid4()
    pl_id = uuid.uuid4()
    validate_target.return_value = {"pipeline_id": str(pl_id)}

    fake = MagicMock(spec=ScheduledOperation)
    fake.id = uuid.uuid4()
    fake.project_id = pid
    fake.name = "Daily"
    fake.description = None
    fake.schedule_type = "transformation_pipeline_run"
    fake.cron_expression = "0 9 * * *"
    fake.timezone = None
    fake.enabled = True
    fake.target_config_json = {"pipeline_id": str(pl_id)}
    fake.created_by_user_id = _user().id
    fake.last_triggered_at = None
    fake.next_run_at = None
    fake.last_run_started_at = None
    fake.last_run_finished_at = None
    fake.last_run_status = None
    fake.last_error_message = None
    fake.execution_count = 0
    fake.created_at = datetime.now(UTC)
    fake.updated_at = datetime.now(UTC)

    db = MagicMock()
    with patch("service_schedules.service.ScheduledOperation", return_value=fake):
        out = create_schedule(
            db,
            project_id=pid,
            payload=ScheduledOperationCreate(
                name="Daily",
                schedule_type="transformation_pipeline_run",
                cron_expression="0 9 * * *",
                target_config={"pipeline_id": str(pl_id)},
            ),
            current_user=_user(),
        )
    assert out.name == "Daily"
    db.add.assert_called_once()
    db.commit.assert_called()


@patch("service_schedules.service._get_schedule_model")
def test_toggle_schedule(mock_get) -> None:
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    row = _schedule_row(sid, pid, "transformation_pipeline_run", {"pipeline_id": str(uuid.uuid4())})
    row.enabled = True
    mock_get.return_value = row
    db = MagicMock()
    out = toggle_schedule(db, project_id=pid, schedule_id=sid, enabled=False, current_user=_user())
    assert out.enabled is False
    db.commit.assert_called()


@patch("service_schedules.service.execute_schedule_operation")
@patch("service_schedules.service._get_schedule_model")
def test_trigger_postgres_reuses_publish(mock_get, mock_exec) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    ds_id = uuid.uuid4()
    dest_id = uuid.uuid4()
    run_read = PipelineRunRead(
        id=uuid.uuid4(),
        project_id=pid,
        triggered_by_user_id=_user().id,
        pipeline_id=None,
        triggered_by_username=None,
        run_type="dataset_publish_postgres",
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
        postgres_publish=DatasetPublishPostgresResponse(
            success=True,
            message="ok",
            run=run_read,
            target_table="t",
            target_schema=None,
            write_mode="append",
            row_count_written=1,
            row_count_attempted=1,
            destination=DestinationPublishSummary(id=dest_id, name="pg", destination_type="postgres"),
            summary_json=None,
        ),
    )
    row = _schedule_row(
        sid,
        pid,
        "postgres_publish",
        {
            "dataset_id": str(ds_id),
            "destination_id": str(dest_id),
            "table_name": "t",
            "write_mode": "append",
        },
    )
    mock_get.return_value = row
    db = MagicMock()
    db.get.return_value = row

    res = trigger_schedule_now(
        db,
        project_id=pid,
        schedule_id=sid,
        current_user=_user(),
        storage_backend=object(),
        settings=object(),
    )
    mock_exec.assert_called_once()
    assert res.success is True
    assert res.postgres_publish is not None


@patch("service_schedules.service.execute_schedule_operation")
@patch("service_schedules.service._get_schedule_model")
def test_trigger_transformation_reuses_pipeline_run(mock_get, mock_exec) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    pl_id = uuid.uuid4()
    mock_exec.return_value = ScheduleExecutionOutcome(
        success=True,
        message="ok",
        triggered_run=PipelineRunRead(
            id=uuid.uuid4(),
            project_id=pid,
            triggered_by_user_id=_user().id,
            pipeline_id=pl_id,
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
        transformation=TransformationRunResponse(
            run=PipelineRunRead(
                id=uuid.uuid4(),
                project_id=pid,
                triggered_by_user_id=_user().id,
                pipeline_id=pl_id,
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
            dataset=_dataset_detail(pid),
        ),
        postgres_publish=None,
    )
    row = _schedule_row(sid, pid, "transformation_pipeline_run", {"pipeline_id": str(pl_id)})
    mock_get.return_value = row
    db = MagicMock()
    db.get.return_value = row

    res = trigger_schedule_now(
        db,
        project_id=pid,
        schedule_id=sid,
        current_user=_user(),
        storage_backend=object(),
        settings=object(),
    )
    mock_exec.assert_called_once()
    assert res.transformation is not None


@patch("service_schedules.service.execute_schedule_operation")
@patch("service_schedules.service._get_schedule_model")
def test_trigger_transformation_failed_outcome(mock_get, mock_exec) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    pl_id = uuid.uuid4()
    rid = uuid.uuid4()
    mock_exec.return_value = ScheduleExecutionOutcome(
        success=False,
        message="no file",
        triggered_run=PipelineRunRead(
            id=rid,
            project_id=pid,
            triggered_by_user_id=_user().id,
            pipeline_id=pl_id,
            triggered_by_username=None,
            run_type="dataset_transformation",
            status="failed",
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

    row = _schedule_row(sid, pid, "transformation_pipeline_run", {"pipeline_id": str(pl_id)})
    mock_get.return_value = row
    db = MagicMock()
    db.get.return_value = row

    res = trigger_schedule_now(
        db,
        project_id=pid,
        schedule_id=sid,
        current_user=_user(),
        storage_backend=object(),
        settings=object(),
    )
    assert res.success is False
    assert res.triggered_run is not None
