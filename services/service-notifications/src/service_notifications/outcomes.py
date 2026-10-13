from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from service_notifications.external_dispatch import dispatch_external_notifications
from service_notifications.service import create_user_notification
from service_pipeline_runs.schemas import PipelineRunRead
from shared_python.logging import get_logger

logger = get_logger(__name__)


def _persist_notification(db: Session, **kwargs: Any) -> None:
    try:
        create_user_notification(db, **kwargs)
    except Exception:
        logger.exception("user_notification_create_failed")
        return

    project_id = kwargs.get("project_id")
    event_type = kwargs.get("type")
    if project_id is not None and isinstance(event_type, str):
        try:
            dispatch_external_notifications(
                db,
                project_id=project_id,
                event_type=event_type,
                title=str(kwargs.get("title", "")),
                message=str(kwargs.get("message", "")),
                level=str(kwargs.get("level", "info")),
            )
        except Exception:
            logger.exception("external_notification_dispatch_unexpected")


def notify_manual_dataset_publish(
    db: Session,
    *,
    run_read: PipelineRunRead,
    success: bool,
) -> None:
    summary = run_read.summary_json or {}
    dataset_name = str(summary.get("dataset_name") or "dataset")
    publish_type = str(summary.get("publish_type") or run_read.run_type or "publish")
    if publish_type == "dataset_publish_postgres" or run_read.run_type == "dataset_publish_postgres":
        target = str(summary.get("target_table") or "PostgreSQL")
        if success:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_succeeded",
                level="success",
                title="Delivered to PostgreSQL",
                message=f"“{dataset_name}” was delivered to the table {target}.",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )
        else:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_failed",
                level="error",
                title="Delivery to PostgreSQL failed",
                message=f"“{dataset_name}” could not be delivered to {target}.",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )
    elif run_read.run_type == "dataset_delivery":
        destination = summary.get("destination") if isinstance(summary.get("destination"), dict) else {}
        label = str(destination.get("label") or "a destination")
        target = str(summary.get("target") or label)
        _persist_notification(
            db,
            user_id=run_read.triggered_by_user_id,
            project_id=run_read.project_id,
            type="dataset_publish_succeeded" if success else "dataset_publish_failed",
            level="success" if success else "error",
            title=f"Delivered to {label}" if success else f"Delivery to {label} failed",
            message=(
                f"“{dataset_name}” was delivered to {target}."
                if success
                else f"“{dataset_name}” could not be delivered to {target}."
            ),
            related_run_id=run_read.id,
            related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
        )
    elif publish_type == "dataset_publish_power_bi" or run_read.run_type == "dataset_publish_power_bi":
        dest = str(summary.get("target_dataset_name") or "Power BI")
        if success:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_succeeded",
                level="success",
                title="Sent to Power BI",
                message=f"“{dataset_name}” was sent to Power BI ({dest}).",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )
        else:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_failed",
                level="error",
                title="Sending to Power BI failed",
                message=f"“{dataset_name}” could not be sent to Power BI.",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )
    elif publish_type == "dataset_publish_tableau" or run_read.run_type == "dataset_publish_tableau":
        ds = str(summary.get("datasource_name") or "Tableau")
        if success:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_succeeded",
                level="success",
                title="Sent to Tableau",
                message=f"“{dataset_name}” was sent to Tableau ({ds}).",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )
        else:
            _persist_notification(
                db,
                user_id=run_read.triggered_by_user_id,
                project_id=run_read.project_id,
                type="dataset_publish_failed",
                level="error",
                title="Sending to Tableau failed",
                message=f"“{dataset_name}” could not be sent to Tableau ({ds}).",
                related_run_id=run_read.id,
                related_dataset_id=_uuid_or_none(summary.get("dataset_id")),
            )


def notify_manual_transformation_run(
    db: Session,
    *,
    run_read: PipelineRunRead,
    success: bool,
) -> None:
    summary = run_read.summary_json or {}
    pipeline_name = str(
        (summary.get("pipeline_name") or (summary.get("pipeline") or {}).get("name") or "Transformation pipeline")
    )
    if success:
        _persist_notification(
            db,
            user_id=run_read.triggered_by_user_id,
            project_id=run_read.project_id,
            type="transformation_run_succeeded",
            level="success",
            title="Recipe finished",
            message=f"The recipe “{pipeline_name}” ran without problems.",
            related_run_id=run_read.id,
            related_pipeline_id=run_read.pipeline_id,
            related_dataset_id=_uuid_or_none((summary.get("derived_dataset") or {}).get("id")),
        )
    else:
        _persist_notification(
            db,
            user_id=run_read.triggered_by_user_id,
            project_id=run_read.project_id,
            type="transformation_run_failed",
            level="error",
            title="Recipe failed",
            message=f"The recipe “{pipeline_name}” did not finish.",
            related_run_id=run_read.id,
            related_pipeline_id=run_read.pipeline_id,
            related_dataset_id=_uuid_or_none((summary.get("base_dataset") or {}).get("id")),
        )


def notify_automated_schedule_outcome(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    schedule_name: str,
    schedule_type: str,
    success: bool,
    detail_message: str | None,
    triggered_run: PipelineRunRead | None,
    is_retry_execution: bool,
) -> None:
    kind = "recipe" if schedule_type == "transformation_pipeline_run" else "delivery to PostgreSQL"
    retry_note = " (retry)" if is_retry_execution else ""
    if success:
        _persist_notification(
            db,
            user_id=user_id,
            project_id=project_id,
            type="schedule_run_succeeded",
            level="success",
            title="Scheduled run finished",
            message=f"The scheduled {kind} “{schedule_name}” ran without problems{retry_note}.",
            related_run_id=triggered_run.id if triggered_run else None,
            related_schedule_id=schedule_id,
            related_pipeline_id=triggered_run.pipeline_id if triggered_run else None,
        )
    else:
        msg = detail_message or "The scheduled run did not complete successfully."
        _persist_notification(
            db,
            user_id=user_id,
            project_id=project_id,
            type="schedule_run_failed",
            level="error",
            title="Scheduled run failed",
            message=f"The scheduled {kind} “{schedule_name}” failed{retry_note}: {msg}",
            related_run_id=triggered_run.id if triggered_run else None,
            related_schedule_id=schedule_id,
            related_pipeline_id=triggered_run.pipeline_id if triggered_run else None,
        )


def notify_workflow_run_outcome(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    workflow_name: str,
    status: str,
    error: str | None = None,
) -> None:
    """Tell the owner when a workflow run does not fully succeed.

    Scheduled and manual pipeline runs already notify; workflow (DAG) runs did
    not, which meant the one kind of run most likely to fail silently -- the
    multi-step one a worker executes with nobody watching -- was the one that
    said nothing. Success is intentionally quiet (every green run would be
    noise); only a failure or a partial finish is worth an interruption.
    """
    if status == "failed":
        detail = f": {error}" if error else "."
        _persist_notification(
            db,
            user_id=user_id,
            project_id=project_id,
            type="workflow_run_failed",
            level="error",
            title="Workflow failed",
            message=f"Workflow “{workflow_name}” failed{detail}",
        )
    elif status == "partial":
        _persist_notification(
            db,
            user_id=user_id,
            project_id=project_id,
            type="workflow_run_partial",
            level="warning",
            title="Workflow finished with problems",
            message=(
                f"Workflow “{workflow_name}” finished, but some steps failed or were skipped. "
                "Open the run to see which."
            ),
        )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
