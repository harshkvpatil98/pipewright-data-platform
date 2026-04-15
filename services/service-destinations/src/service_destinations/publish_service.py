from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_datasets.service import get_dataset_model_for_project
from service_ingestion.parsers import parse_tabular_file
from service_notifications.outcomes import notify_manual_dataset_publish
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, MisconfiguredEnvironmentError

from service_destinations.at_rest_config import destination_config_for_internal_use
from service_destinations.postgres_writer import validate_table_identifier, write_dataframe_to_postgres
from service_destinations.publish_schemas import (
    DatasetPublishPostgresRequest,
    DatasetPublishPostgresResponse,
    DestinationPublishSummary,
)
from service_destinations.service import get_destination_model


def _log_event(stage: str, message: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
    event: dict[str, object] = {
        "stage": stage,
        "message": message,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if details:
        event["details"] = details
    return event


def _build_log_events(events: list[dict[str, object]]) -> dict[str, object]:
    return {"events": events}


def _load_dataframe(dataset: Dataset, storage_backend: Any) -> pd.DataFrame:
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("Dataset has no stored file artifact to publish.")
    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise BadRequestError("Stored dataset file was not found.") from exc
    except OSError as exc:
        raise BadRequestError(f"Unable to read dataset file: {exc}") from exc
    parsed = parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type)
    return parsed.dataframe


def publish_dataset_to_postgres(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetPublishPostgresRequest,
    current_user: UserRead,
    storage_backend: Any,
    notify_on_complete: bool = True,
) -> DatasetPublishPostgresResponse:
    ensure_owned_project(db, project_id, current_user.id)
    table_name = validate_table_identifier(payload.table_name)

    dest = get_destination_model(db, project_id, payload.destination_id)
    if dest.destination_type != "postgres":
        raise BadRequestError("Destination must be a PostgreSQL destination for this operation.")
    if dest.status != "active":
        raise BadRequestError("Destination is disabled.")

    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    log_events: list[dict[str, object]] = [
        _log_event(
            "queued",
            "Publish request accepted.",
            details={
                "dataset_id": str(dataset_id),
                "destination_id": str(payload.destination_id),
                "table_name": table_name,
                "write_mode": payload.write_mode,
            },
        )
    ]
    current_stage = "queued"

    run = create_pipeline_run(
        db,
        project_id=project_id,
        current_user=current_user,
        run_type="dataset_publish_postgres",
        logs_json=_build_log_events(log_events),
    )

    log_events.append(_log_event("running", "Publish started."))
    mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

    try:
        cfg = destination_config_for_internal_use("postgres", dict(dest.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Publish failed.",
                details={"error": str(exc.detail), "failure_stage": "decrypt_config"},
            )
        )
        summary_fail: dict[str, Any] = {
            "publish_type": "dataset_publish_postgres",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "destination_id": str(dest.id),
            "destination_name": dest.name,
            "destination_type": dest.destination_type,
            "target_table": table_name,
            "target_schema": None,
            "write_mode": payload.write_mode,
            "failure_stage": "decrypt_config",
            "error": str(exc.detail),
        }
        run_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json=summary_fail,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=False)
        return DatasetPublishPostgresResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            target_table=table_name,
            target_schema=None,
            write_mode=payload.write_mode,
            row_count_written=None,
            row_count_attempted=None,
            destination=DestinationPublishSummary(
                id=dest.id,
                name=dest.name,
                destination_type=dest.destination_type,
            ),
            summary_json=summary_fail,
        )

    try:
        current_stage = "load_dataset"
        log_events.append(_log_event("load_dataset", "Loading dataset artifact from storage."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        df = _load_dataframe(dataset, storage_backend)
        row_attempted = int(len(df))
        if row_attempted == 0:
            raise BadRequestError("Dataset has no rows to publish.")

        current_stage = "parse"
        log_events.append(_log_event("parse", f"Parsed {row_attempted} rows for publishing."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "connect_destination"
        log_events.append(_log_event("connect_destination", "Connecting to PostgreSQL destination."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "write_table"
        log_events.append(
            _log_event(
                "write_table",
                f"Writing to table {table_name} ({payload.write_mode}).",
            )
        )
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        rows_written = write_dataframe_to_postgres(
            df,
            config=cfg,
            table_name=table_name,
            write_mode=payload.write_mode,
        )

        target_schema = cfg.get("schema")
        if isinstance(target_schema, str):
            target_schema = target_schema.strip() or None
        else:
            target_schema = None

        summary_json: dict[str, Any] = {
            "publish_type": "dataset_publish_postgres",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "destination_id": str(dest.id),
            "destination_name": dest.name,
            "destination_type": dest.destination_type,
            "target_table": table_name,
            "target_schema": target_schema,
            "write_mode": payload.write_mode,
            "row_count_attempted": row_attempted,
            "row_count_written": rows_written,
        }

        log_events.append(
            _log_event("finalize", f"Published {rows_written} rows to {table_name}."),
        )

        run_read = mark_pipeline_run_succeeded(
            db,
            run=run,
            summary_json=summary_json,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=True)

        return DatasetPublishPostgresResponse(
            success=True,
            message=f"Published {rows_written} rows to {table_name}.",
            run=run_read,
            target_table=table_name,
            target_schema=target_schema,
            write_mode=payload.write_mode,
            row_count_written=rows_written,
            row_count_attempted=row_attempted,
            destination=DestinationPublishSummary(
                id=dest.id,
                name=dest.name,
                destination_type=dest.destination_type,
            ),
            summary_json=summary_json,
        )

    except BadRequestError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Publish failed.",
                details={"error": exc.detail, "failure_stage": current_stage},
            )
        )
        summary_fail: dict[str, Any] = {
            "publish_type": "dataset_publish_postgres",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "destination_id": str(dest.id),
            "destination_name": dest.name,
            "destination_type": dest.destination_type,
            "target_table": table_name,
            "target_schema": cfg.get("schema") if isinstance(cfg.get("schema"), str) else None,
            "write_mode": payload.write_mode,
            "failure_stage": current_stage,
            "error": exc.detail,
        }
        run_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json=summary_fail,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=False)
        return DatasetPublishPostgresResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            target_table=table_name,
            target_schema=summary_fail.get("target_schema"),
            write_mode=payload.write_mode,
            row_count_written=None,
            row_count_attempted=None,
            destination=DestinationPublishSummary(
                id=dest.id,
                name=dest.name,
                destination_type=dest.destination_type,
            ),
            summary_json=summary_fail,
        )

    except Exception as exc:  # noqa: BLE001
        log_events.append(
            _log_event(
                "failed",
                "Publish failed due to an unexpected error.",
                details={"failure_stage": current_stage},
            )
        )
        summary_unexpected: dict[str, Any] = {
            "publish_type": "dataset_publish_postgres",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "destination_id": str(dest.id),
            "destination_name": dest.name,
            "destination_type": dest.destination_type,
            "target_table": table_name,
            "write_mode": payload.write_mode,
            "failure_stage": current_stage,
            "error": "An unexpected error occurred during publish.",
        }
        run_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json=summary_unexpected,
            logs_json=_build_log_events(log_events),
        )
        _ = exc
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=False)
        return DatasetPublishPostgresResponse(
            success=False,
            message="Publish failed due to an unexpected error.",
            run=run_read,
            target_table=table_name,
            target_schema=None,
            write_mode=payload.write_mode,
            row_count_written=None,
            row_count_attempted=None,
            destination=DestinationPublishSummary(
                id=dest.id,
                name=dest.name,
                destination_type=dest.destination_type,
            ),
            summary_json=summary_unexpected,
        )
