from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
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
from service_destinations.bi_service import get_bi_connection_model
from service_destinations.connectors.power_bi_publish import publish_dataframe_power_bi_push
from service_destinations.postgres_writer import validate_table_identifier
from service_destinations.publish_schemas import (
    BiConnectionPublishSummary,
    DatasetPublishPowerBiRequest,
    DatasetPublishPowerBiResponse,
)
from service_destinations.publish_service import _build_log_events, _load_dataframe, _log_event


def publish_dataset_to_power_bi(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetPublishPowerBiRequest,
    current_user: UserRead,
    storage_backend: Any,
    notify_on_complete: bool = True,
) -> DatasetPublishPowerBiResponse:
    ensure_owned_project(db, project_id, current_user.id)

    conn = get_bi_connection_model(db, project_id, payload.connection_id)
    if conn.destination_type != "power_bi":
        raise BadRequestError("Connection must be a Power BI integration.")
    if conn.status != "active":
        raise BadRequestError("Power BI connection is disabled.")

    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    table_name = validate_table_identifier(payload.target_table_name or "PublishedData")
    workspace_id_str = str(payload.workspace_id)

    log_events: list[dict[str, object]] = [
        _log_event(
            "queued",
            "Power BI publish request accepted.",
            details={
                "dataset_id": str(dataset_id),
                "connection_id": str(payload.connection_id),
                "workspace_id": workspace_id_str,
                "target_dataset_name": payload.target_dataset_name.strip(),
                "target_table_name": table_name,
                "write_mode": payload.write_mode,
            },
        )
    ]
    current_stage = "queued"

    run = create_pipeline_run(
        db,
        project_id=project_id,
        current_user=current_user,
        run_type="dataset_publish_power_bi",
        logs_json=_build_log_events(log_events),
    )

    log_events.append(_log_event("running", "Power BI publish started."))
    mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

    conn_summary = BiConnectionPublishSummary(id=conn.id, name=conn.name, integration_type="power_bi")

    current_stage = "decrypt_config"
    try:
        cfg = destination_config_for_internal_use("power_bi", dict(conn.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Power BI publish failed.",
                details={"error": str(exc.detail), "failure_stage": current_stage},
            )
        )
        summary_key: dict[str, Any] = {
            "publish_type": "dataset_publish_power_bi",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "workspace_id": workspace_id_str,
            "target_dataset_name": payload.target_dataset_name.strip(),
            "target_table_name": table_name,
            "write_mode": payload.write_mode,
            "failure_stage": current_stage,
            "error": str(exc.detail),
        }
        run_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json=summary_key,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=False)
        return DatasetPublishPowerBiResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            connection=conn_summary,
            workspace_id=payload.workspace_id,
            target_dataset_name=payload.target_dataset_name.strip(),
            target_table_name=table_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            power_bi_dataset_id=None,
            provider_outcome=None,
            summary_json=summary_key,
        )

    try:
        current_stage = "load_dataset"
        log_events.append(_log_event("load_dataset", "Loading dataset artifact from storage."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        df: pd.DataFrame = _load_dataframe(dataset, storage_backend)
        row_attempted = int(len(df))
        if row_attempted == 0:
            raise BadRequestError("Dataset has no rows to publish.")

        current_stage = "parse"
        log_events.append(_log_event("parse", f"Parsed {row_attempted} rows for Power BI push."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "authenticate_power_bi"
        log_events.append(_log_event("authenticate_power_bi", "Obtaining access token for Power BI."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "validate_workspace"
        log_events.append(_log_event("validate_workspace", "Validating workspace and push dataset target."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "create_or_resolve_target"
        log_events.append(
            _log_event(
                "create_or_resolve_target",
                f"Applying write_mode={payload.write_mode} for push dataset.",
            )
        )
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "push_rows"
        log_events.append(_log_event("push_rows", "Uploading rows to Power BI in batches."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        schema_hint = dataset.schema_json if isinstance(dataset.schema_json, dict) else None
        outcome = publish_dataframe_power_bi_push(
            power_bi_config=cfg,
            workspace_id=workspace_id_str,
            target_dataset_name=payload.target_dataset_name,
            target_table_name=table_name,
            df=df,
            write_mode=payload.write_mode,
            schema_json=schema_hint,
        )

        summary_json: dict[str, Any] = {
            "publish_type": "dataset_publish_power_bi",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "workspace_id": workspace_id_str,
            "target_dataset_name": outcome.target_dataset_name,
            "target_table_name": outcome.target_table_name,
            "write_mode": payload.write_mode,
            "row_count_attempted": row_attempted,
            "row_count_published": outcome.rows_published,
            "power_bi_dataset_id": outcome.dataset_id,
            "provider_publish_mode": outcome.publish_mode,
        }

        log_events.append(
            _log_event(
                "finalize",
                f"Published {outcome.rows_published} rows to Power BI dataset {outcome.target_dataset_name}.",
            )
        )

        run_read = mark_pipeline_run_succeeded(
            db,
            run=run,
            summary_json=summary_json,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=True)

        return DatasetPublishPowerBiResponse(
            success=True,
            message=f"Published {outcome.rows_published} rows to Power BI.",
            run=run_read,
            connection=conn_summary,
            workspace_id=payload.workspace_id,
            target_dataset_name=outcome.target_dataset_name,
            target_table_name=outcome.target_table_name,
            write_mode=payload.write_mode,
            row_count_published=outcome.rows_published,
            row_count_attempted=row_attempted,
            power_bi_dataset_id=outcome.dataset_id,
            provider_outcome=outcome.publish_mode,
            summary_json=summary_json,
        )

    except BadRequestError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Power BI publish failed.",
                details={"error": exc.detail, "failure_stage": current_stage},
            )
        )
        summary_fail: dict[str, Any] = {
            "publish_type": "dataset_publish_power_bi",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "workspace_id": workspace_id_str,
            "target_dataset_name": payload.target_dataset_name.strip(),
            "target_table_name": table_name,
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
        return DatasetPublishPowerBiResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            connection=conn_summary,
            workspace_id=payload.workspace_id,
            target_dataset_name=payload.target_dataset_name.strip(),
            target_table_name=table_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            power_bi_dataset_id=None,
            provider_outcome=None,
            summary_json=summary_fail,
        )

    except Exception as exc:  # noqa: BLE001
        log_events.append(
            _log_event(
                "failed",
                "Power BI publish failed due to an unexpected error.",
                details={"failure_stage": current_stage},
            )
        )
        summary_unexpected: dict[str, Any] = {
            "publish_type": "dataset_publish_power_bi",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "workspace_id": workspace_id_str,
            "target_dataset_name": payload.target_dataset_name.strip(),
            "target_table_name": table_name,
            "write_mode": payload.write_mode,
            "failure_stage": current_stage,
            "error": "An unexpected error occurred during Power BI publish.",
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
        return DatasetPublishPowerBiResponse(
            success=False,
            message="Power BI publish failed due to an unexpected error.",
            run=run_read,
            connection=conn_summary,
            workspace_id=payload.workspace_id,
            target_dataset_name=payload.target_dataset_name.strip(),
            target_table_name=table_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            power_bi_dataset_id=None,
            provider_outcome=None,
            summary_json=summary_unexpected,
        )
