from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_pipeline_runs.audit import build_run_audit_summary
from service_pipeline_runs.contracts import get_pipeline_run_for_project
from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.schemas import (
    PipelineRunListResponse,
    PipelineRunRead,
    RunAuditSummary,
    RunOutputVersion,
)
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


def _snapshot(logs_json: dict[str, object] | None) -> dict[str, object] | None:
    """A copy of a run's log as it is now.

    Producers keep one list of events and append to it as they go. Storing
    that list itself meant the value already held and each new one were the
    same object, so a later change was never seen as one and never written:
    every failed recipe run and import kept only "Waiting to start." (found
    in C1). A copy each time makes every change a change.
    """
    return copy.deepcopy(logs_json) if logs_json is not None else None


def create_pipeline_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    current_user: UserRead,
    run_type: str,
    pipeline_id: uuid.UUID | None = None,
    logs_json: dict[str, object] | None = None,
) -> PipelineRun:
    from service_pipeline_runs.limits import current_origin

    ensure_owned_project(db, project_id, current_user.id)
    run = PipelineRun(
        project_id=project_id,
        triggered_by_user_id=current_user.id,
        pipeline_id=pipeline_id,
        run_type=run_type,
        status="queued",
        logs_json=_snapshot(logs_json),
        origin=current_origin(),
    )
    db.add(run)
    db.flush()
    return run


def mark_pipeline_run_running(
    db: Session, *, run: PipelineRun, logs_json: dict[str, object] | None = None
) -> PipelineRun:
    """Start a run, or record its progress while it runs.

    Starting one a person asked for while their project already has its
    limit going is refused (D2, O8); queued work is held back by the worker
    instead. Progress keeps the time it started: it used to be reset on
    every update, so a run's duration was the time since its last step.
    """
    if run.status != "running":
        if run.origin == "person":
            from service_pipeline_runs.limits import admit

            admit(db, run.project_id)
        run.started_at = datetime.now(UTC)
    run.status = "running"
    if logs_json is not None:
        run.logs_json = _snapshot(logs_json)
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
    run.logs_json = _snapshot(logs_json)
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
    run.logs_json = _snapshot(logs_json)
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
    summary = build_run_audit_summary(run=run)
    summary.output_versions = _output_versions(db, run.id)
    summary.execution_context = _execution_context(run)
    summary.replayable, summary.replay_reason = _replayability(run)
    _name_things(db, run, summary)
    return summary


def _name_things(db: Session, run: PipelineRun, summary: RunAuditSummary) -> None:
    """Fill in names for the ids the page shows: who, which recipe, which datasets."""
    from service_auth.models import User
    from service_datasets.models import Dataset
    from service_transformations.models import TransformationPipeline

    user = db.get(User, run.triggered_by_user_id)
    if user is not None:
        summary.triggered_by_name = user.display_name or user.username
    if run.pipeline_id is not None:
        pipeline = db.get(TransformationPipeline, run.pipeline_id)
        summary.pipeline_name = pipeline.name if pipeline is not None else None

    ids: set[uuid.UUID] = set(summary.related_dataset_ids)
    ids.update(version.dataset_id for version in summary.output_versions)
    context = summary.execution_context or {}
    pins = list(context.get("inputs") or []) + list(context.get("outputs") or [])
    for pin in pins:
        if isinstance(pin, dict) and pin.get("dataset_id"):
            try:
                ids.add(uuid.UUID(str(pin["dataset_id"])))
            except ValueError:
                continue
    if ids:
        rows = db.execute(select(Dataset.id, Dataset.name).where(Dataset.id.in_(ids))).all()
        summary.dataset_names = {str(row.id): row.name for row in rows}


def _output_versions(db: Session, run_id: uuid.UUID) -> list[RunOutputVersion]:
    # Function-level import: datasets is a peer service; this reads its public
    # model through the version table's own run link, nothing internal.
    from service_datasets.models import Dataset, DatasetVersion

    rows = db.execute(
        select(DatasetVersion, Dataset.name)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(DatasetVersion.pipeline_run_id == run_id)
        .order_by(DatasetVersion.created_at)
    ).all()
    return [
        RunOutputVersion(
            dataset_id=version.dataset_id,
            dataset_name=name,
            version_number=version.version_number,
            content_hash=version.content_hash,
            retention_state=version.retention_state,
        )
        for version, name in rows
    ]


def _execution_context(run: PipelineRun) -> dict[str, Any] | None:
    summary = run.summary_json if isinstance(run.summary_json, dict) else None
    context = summary.get("execution_context") if summary else None
    return context if isinstance(context, dict) else None


def _replayability(run: PipelineRun) -> tuple[bool, str | None]:
    # The rule lives with replay itself so the page and the endpoint agree.
    from service_transformations.replay import replayability

    ok, reason, _context = replayability(run)
    return ok, reason


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
        logs_json={"events": [{"stage": "queued", "message": "Waiting to start."}]},
    )
    mark_pipeline_run_running(
        db,
        run=run,
        logs_json={
            "events": [
                {"stage": "queued", "message": "Waiting to start."},
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
                {"stage": "queued", "message": "Waiting to start."},
                {"stage": "running", "message": "Collecting project-scoped platform counts."},
                {"stage": "succeeded", "message": "Sample run completed successfully."},
            ]
        },
    )
