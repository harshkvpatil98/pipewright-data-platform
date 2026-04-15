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
from service_destinations.connectors.tableau_publish import (
    publish_dataframe_to_tableau_datasource,
    validate_tableau_datasource_name,
)
from service_destinations.publish_schemas import (
    BiConnectionPublishSummary,
    DatasetPublishTableauRequest,
    DatasetPublishTableauResponse,
)
from service_destinations.publish_service import _build_log_events, _load_dataframe, _log_event


def publish_dataset_to_tableau(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetPublishTableauRequest,
    current_user: UserRead,
    storage_backend: Any,
    notify_on_complete: bool = True,
) -> DatasetPublishTableauResponse:
    ensure_owned_project(db, project_id, current_user.id)

    conn = get_bi_connection_model(db, project_id, payload.connection_id)
    if conn.destination_type != "tableau":
        raise BadRequestError("Connection must be a Tableau integration.")
    if conn.status != "active":
        raise BadRequestError("Tableau connection is disabled.")

    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    ds_name = validate_tableau_datasource_name(payload.datasource_name)
    project_id_str = str(payload.tableau_project_id)

    log_events: list[dict[str, object]] = [
        _log_event(
            "queued",
            "Tableau publish request accepted.",
            details={
                "dataset_id": str(dataset_id),
                "connection_id": str(payload.connection_id),
                "tableau_project_id": project_id_str,
                "datasource_name": ds_name,
                "write_mode": payload.write_mode,
            },
        )
    ]
    current_stage = "queued"

    run = create_pipeline_run(
        db,
        project_id=project_id,
        current_user=current_user,
        run_type="dataset_publish_tableau",
        logs_json=_build_log_events(log_events),
    )

    log_events.append(_log_event("running", "Tableau publish started."))
    mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

    conn_summary = BiConnectionPublishSummary(id=conn.id, name=conn.name, integration_type="tableau")

    current_stage = "decrypt_config"
    try:
        cfg = destination_config_for_internal_use("tableau", dict(conn.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Tableau publish failed.",
                details={"error": str(exc.detail), "failure_stage": current_stage},
            )
        )
        summary_key: dict[str, Any] = {
            "publish_type": "dataset_publish_tableau",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "tableau_project_id": project_id_str,
            "datasource_name": ds_name,
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
        return DatasetPublishTableauResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            connection=conn_summary,
            tableau_site_id=None,
            tableau_project_id=payload.tableau_project_id,
            datasource_name=ds_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            tableau_datasource_id=None,
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
        log_events.append(_log_event("parse", f"Parsed {row_attempted} rows for Tableau Hyper publish."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "authenticate_tableau"
        log_events.append(_log_event("authenticate_tableau", "Signing in to Tableau REST API."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "resolve_project"
        log_events.append(_log_event("resolve_project", "Validating target Tableau project."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "prepare_publish_artifact"
        log_events.append(_log_event("prepare_publish_artifact", "Building Hyper extract from dataframe."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        current_stage = "publish_datasource"
        log_events.append(_log_event("publish_datasource", "Uploading datasource to Tableau Server."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        outcome = publish_dataframe_to_tableau_datasource(
            tableau_config=cfg,
            tableau_project_id=project_id_str,
            datasource_name=payload.datasource_name,
            df=df,
            write_mode=payload.write_mode,
        )

        summary_json: dict[str, Any] = {
            "publish_type": "dataset_publish_tableau",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "tableau_site_id": outcome.site_id,
            "tableau_project_id": project_id_str,
            "datasource_name": outcome.datasource_name,
            "write_mode": payload.write_mode,
            "row_count_attempted": row_attempted,
            "row_count_published": outcome.rows_published,
            "tableau_datasource_id": outcome.datasource_id,
            "provider_publish_mode": outcome.publish_mode,
        }

        log_events.append(
            _log_event(
                "finalize",
                f"Published datasource {outcome.datasource_name} with {outcome.rows_published} rows.",
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

        return DatasetPublishTableauResponse(
            success=True,
            message=f"Published {outcome.rows_published} rows to Tableau as {outcome.datasource_name}.",
            run=run_read,
            connection=conn_summary,
            tableau_site_id=outcome.site_id,
            tableau_project_id=payload.tableau_project_id,
            datasource_name=outcome.datasource_name,
            write_mode=payload.write_mode,
            row_count_published=outcome.rows_published,
            row_count_attempted=row_attempted,
            tableau_datasource_id=outcome.datasource_id,
            provider_outcome=outcome.publish_mode,
            summary_json=summary_json,
        )

    except BadRequestError as exc:
        log_events.append(
            _log_event(
                "failed",
                "Tableau publish failed.",
                details={"error": exc.detail, "failure_stage": current_stage},
            )
        )
        summary_fail: dict[str, Any] = {
            "publish_type": "dataset_publish_tableau",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "tableau_project_id": project_id_str,
            "datasource_name": ds_name,
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
        return DatasetPublishTableauResponse(
            success=False,
            message=str(exc.detail),
            run=run_read,
            connection=conn_summary,
            tableau_site_id=None,
            tableau_project_id=payload.tableau_project_id,
            datasource_name=ds_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            tableau_datasource_id=None,
            provider_outcome=None,
            summary_json=summary_fail,
        )

    except Exception as exc:  # noqa: BLE001
        log_events.append(
            _log_event(
                "failed",
                "Tableau publish failed due to an unexpected error.",
                details={"failure_stage": current_stage},
            )
        )
        summary_unexpected: dict[str, Any] = {
            "publish_type": "dataset_publish_tableau",
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "connection_id": str(conn.id),
            "connection_name": conn.name,
            "tableau_project_id": project_id_str,
            "datasource_name": ds_name,
            "write_mode": payload.write_mode,
            "failure_stage": current_stage,
            "error": "An unexpected error occurred during Tableau publish.",
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
        return DatasetPublishTableauResponse(
            success=False,
            message="Tableau publish failed due to an unexpected error.",
            run=run_read,
            connection=conn_summary,
            tableau_site_id=None,
            tableau_project_id=payload.tableau_project_id,
            datasource_name=ds_name,
            write_mode=payload.write_mode,
            row_count_published=None,
            row_count_attempted=None,
            tableau_datasource_id=None,
            provider_outcome=None,
            summary_json=summary_unexpected,
        )
