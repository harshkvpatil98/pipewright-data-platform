from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_destinations.publish_schemas import DatasetPublishPostgresRequest, DatasetPublishPostgresResponse
from service_destinations.publish_service import publish_dataset_to_postgres
from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.schemas import PipelineRunRead
from service_pipeline_runs.service import get_pipeline_run
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import TransformationRunResponse
from shared_python.errors import ApplicationError, BadRequestError

from service_schedules.models import ScheduledOperation


@dataclass
class ScheduleExecutionOutcome:
    success: bool
    message: str
    triggered_run: PipelineRunRead | None
    transformation: TransformationRunResponse | None
    postgres_publish: DatasetPublishPostgresResponse | None


def _latest_pipeline_run_for_pipeline(
    db: Session, *, project_id: uuid.UUID, pipeline_id: uuid.UUID
) -> PipelineRun | None:
    return db.scalars(
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id, PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.created_at.desc())
        .limit(1)
    ).first()


def execute_schedule_operation(
    db: Session,
    *,
    row: ScheduledOperation,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
    notify_on_complete: bool = True,
) -> ScheduleExecutionOutcome:
    """Run transformation or postgres publish for a schedule row (no ownership check)."""
    cfg = dict(row.target_config_json or {})
    project_id = row.project_id

    if row.schedule_type == "transformation_pipeline_run":
        try:
            pipeline_id = uuid.UUID(str(cfg["pipeline_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise BadRequestError("Schedule target is missing a valid pipeline_id.") from exc
        try:
            result = run_saved_transformation_pipeline(
                db,
                project_id=project_id,
                pipeline_id=pipeline_id,
                current_user=current_user,
                storage_backend=storage_backend,
                settings=settings,
                notify_on_complete=notify_on_complete,
            )
            return ScheduleExecutionOutcome(
                success=True,
                message="Transformation pipeline run completed.",
                triggered_run=result.run,
                transformation=result,
                postgres_publish=None,
            )
        except ApplicationError as exc:
            latest = _latest_pipeline_run_for_pipeline(db, project_id=project_id, pipeline_id=pipeline_id)
            triggered = get_pipeline_run(db, project_id, latest.id, current_user) if latest else None
            return ScheduleExecutionOutcome(
                success=False,
                message=str(exc.detail),
                triggered_run=triggered,
                transformation=None,
                postgres_publish=None,
            )

    if row.schedule_type == "postgres_publish":
        try:
            req = DatasetPublishPostgresRequest(
                destination_id=uuid.UUID(str(cfg["destination_id"])),
                table_name=str(cfg["table_name"]),
                write_mode=cfg["write_mode"],  # type: ignore[arg-type]
            )
            dataset_id = uuid.UUID(str(cfg["dataset_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise BadRequestError("Schedule target is missing valid postgres publish fields.") from exc
        pub = publish_dataset_to_postgres(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=req,
            current_user=current_user,
            storage_backend=storage_backend,
            notify_on_complete=notify_on_complete,
        )
        return ScheduleExecutionOutcome(
            success=pub.success,
            message=pub.message,
            triggered_run=pub.run,
            transformation=None,
            postgres_publish=pub,
        )

    raise BadRequestError("Unsupported schedule type.")
