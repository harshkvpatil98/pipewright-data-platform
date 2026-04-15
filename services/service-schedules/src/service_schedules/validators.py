from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from croniter import croniter
from sqlalchemy.orm import Session

from service_destinations.postgres_writer import validate_table_identifier
from service_destinations.service import get_destination_model
from service_datasets.service import get_dataset_model_for_project
from service_transformations.contracts import get_transformation_pipeline_for_project
from shared_python.errors import BadRequestError

ScheduleType = Literal["transformation_pipeline_run", "postgres_publish"]
WRITE_MODES = frozenset({"replace", "append"})


def validate_cron_expression(expr: str) -> str:
    cleaned = expr.strip()
    if not cleaned:
        raise BadRequestError("Cron expression is required.")
    if len(cleaned) > 512:
        raise BadRequestError("Cron expression is too long.")
    try:
        croniter(cleaned, datetime.now())
    except (ValueError, KeyError, TypeError) as exc:
        raise BadRequestError("Invalid cron expression. Use a standard five-field cron string.") from exc
    return cleaned


def validate_and_normalize_target_config(
    db: Session,
    *,
    project_id: uuid.UUID,
    schedule_type: ScheduleType,
    target: dict[str, Any],
) -> dict[str, Any]:
    if schedule_type == "transformation_pipeline_run":
        raw_pid = target.get("pipeline_id")
        if raw_pid is None:
            raise BadRequestError("target_config.pipeline_id is required.")
        try:
            pipeline_id = uuid.UUID(str(raw_pid))
        except (ValueError, TypeError) as exc:
            raise BadRequestError("target_config.pipeline_id must be a UUID.") from exc
        if len(target) != 1 or "pipeline_id" not in target:
            raise BadRequestError("target_config for transformation_pipeline_run must only contain pipeline_id.")
        get_transformation_pipeline_for_project(db, project_id, pipeline_id)
        return {"pipeline_id": str(pipeline_id)}

    if schedule_type == "postgres_publish":
        required = ("dataset_id", "destination_id", "table_name", "write_mode")
        for key in required:
            if key not in target:
                raise BadRequestError(f"target_config.{key} is required for postgres_publish.")
        extra = set(target.keys()) - set(required)
        if extra:
            raise BadRequestError(f"Unexpected keys in target_config: {sorted(extra)}.")
        try:
            dataset_id = uuid.UUID(str(target["dataset_id"]))
            destination_id = uuid.UUID(str(target["destination_id"]))
        except (ValueError, TypeError) as exc:
            raise BadRequestError("dataset_id and destination_id must be UUIDs.") from exc
        table_name = validate_table_identifier(str(target["table_name"]))
        write_mode = str(target["write_mode"])
        if write_mode not in WRITE_MODES:
            raise BadRequestError('write_mode must be "replace" or "append".')
        ds = get_dataset_model_for_project(db, project_id, dataset_id)
        dest = get_destination_model(db, project_id, destination_id)
        if dest.destination_type != "postgres":
            raise BadRequestError("Destination must be PostgreSQL for this schedule type.")
        if dest.status != "active":
            raise BadRequestError("Destination is disabled.")
        if not ds.file_path or not ds.file_type:
            raise BadRequestError("Dataset has no stored file artifact to publish.")
        return {
            "dataset_id": str(dataset_id),
            "destination_id": str(destination_id),
            "table_name": table_name,
            "write_mode": write_mode,
        }

    raise BadRequestError("Unsupported schedule_type.")
