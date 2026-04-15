from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_pipeline_runs.audit import build_run_audit_summary
from service_pipeline_runs.contracts import get_pipeline_run_for_project
from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.schemas import PipelineRunListResponse, PipelineRunRead, RunAuditSummary
from service_projects.contracts import (
    count_project_datasets,
    count_project_runs,
    count_project_sources,
    ensure_owned_project,
)
from service_sources.contracts import total_sources


def _serialize_run(run: PipelineRun) -> PipelineRunRead:
    triggered_by_username = getattr(run, "triggered_by_username", None)
    if getattr(run, "triggered_by_user", None) is not None:
        triggered_by_username = run.triggered_by_user.username
    return PipelineRunRead(
        id=run.id,
        project_id=run.project_id,
        triggered_by_user_id=run.triggered_by_user_id,
        pipeline_id=run.pipeline_id,
        triggered_by_username=triggered_by_username,
        run_type=run.run_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        summary_json=run.summary_json,
        logs_json=run.logs_json,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def create_pipeline_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    current_user: UserRead,
    run_type: str,
    pipeline_id: uuid.UUID | None = None,
    logs_json: dict[str, object] | None = None,
) -> PipelineRun:
    ensure_owned_project(db, project_id, current_user.id)
    run = PipelineRun(
        project_id=project_id,
        triggered_by_user_id=current_user.id,
        pipeline_id=pipeline_id,
        run_type=run_type,
        status="queued",
        logs_json=logs_json,
    )
    db.add(run)
    db.flush()
    return run


def mark_pipeline_run_running(
    db: Session, *, run: PipelineRun, logs_json: dict[str, object] | None = None
) -> PipelineRun:
    run.status = "running"
    run.started_at = datetime.now(UTC)
    if logs_json is not None:
        run.logs_json = logs_json
    db.flush()
    return run


def mark_pipeline_run_succeeded(
    db: Session,
    *,
    run: PipelineRun,
    summary_json: dict[str, object] | None = None,
    logs_json: dict[str, object] | None = None,
) -> PipelineRunRead:
    run.status = "succeeded"
    run.completed_at = datetime.now(UTC)
    run.summary_json = summary_json
    run.logs_json = logs_json
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


def mark_pipeline_run_failed(
    db: Session,
    *,
    run: PipelineRun,
    summary_json: dict[str, object] | None = None,
    logs_json: dict[str, object] | None = None,
) -> PipelineRunRead:
    run.status = "failed"
    run.completed_at = datetime.now(UTC)
    run.summary_json = summary_json
    run.logs_json = logs_json
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


def list_pipeline_runs(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> PipelineRunListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    runs = db.scalars(
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id)
        .order_by(PipelineRun.created_at.desc())
    ).all()
    return PipelineRunListResponse(items=[_serialize_run(run) for run in runs])


def get_pipeline_run(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID, current_user: UserRead
) -> PipelineRunRead:
    ensure_owned_project(db, project_id, current_user.id)
    run = get_pipeline_run_for_project(db, project_id, run_id)
    return _serialize_run(run)


def get_run_audit_summary(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID, current_user: UserRead
) -> RunAuditSummary:
    ensure_owned_project(db, project_id, current_user.id)
    run = get_pipeline_run_for_project(db, project_id, run_id)
    return build_run_audit_summary(run=run)


# The sample run is synchronous today, but the persisted record shape is ready for future async execution.
def create_sample_pipeline_run(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> PipelineRunRead:
    project = ensure_owned_project(db, project_id, current_user.id)
    run = create_pipeline_run(
        db,
        project_id=project.id,
        current_user=current_user,
        run_type="sample_orchestration",
        logs_json={"events": [{"stage": "queued", "message": "Run accepted by the gateway."}]},
    )
    mark_pipeline_run_running(
        db,
        run=run,
        logs_json={
            "events": [
                {"stage": "queued", "message": "Run accepted by the gateway."},
                {"stage": "running", "message": "Collecting project-scoped platform counts."},
            ]
        },
    )
    return mark_pipeline_run_succeeded(
        db,
        run=run,
        summary_json={
            "project_slug": project.slug,
            "project_status": project.status,
            "project_source_count": count_project_sources(db, project.id),
            "project_dataset_count": count_project_datasets(db, project.id),
            "project_run_count": count_project_runs(db, project.id) + 1,
            "global_source_count_snapshot": total_sources(db),
        },
        logs_json={
            "events": [
                {"stage": "queued", "message": "Run accepted by the gateway."},
                {"stage": "running", "message": "Collecting project-scoped platform counts."},
                {"stage": "succeeded", "message": "Sample run completed successfully."},
            ]
        },
    )
