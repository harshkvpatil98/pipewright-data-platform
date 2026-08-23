"""Persistence and API-facing operations for schema drift."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from service_quality.drift import DriftReport, detect_schema_drift
from service_quality.models import SchemaDriftEvent
from service_quality.schemas_drift import (
    SchemaDriftComparisonResponse,
    SchemaDriftEventListResponse,
    SchemaDriftEventRead,
)
from shared_python.errors import BadRequestError, NotFoundError

MAX_EVENT_HISTORY = 200


def record_drift_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID | None,
    previous_dataset_id: uuid.UUID | None,
    report: DriftReport,
    extraction_job_id: uuid.UUID | None = None,
) -> SchemaDriftEvent | None:
    """Persist a drift event, or nothing when the schema did not change.

    Callers commit; this only stages the row so it joins the caller's transaction.
    """
    if not report.has_drift:
        return None

    event = SchemaDriftEvent(
        project_id=project_id,
        dataset_id=dataset_id,
        previous_dataset_id=previous_dataset_id,
        extraction_job_id=extraction_job_id,
        severity=report.severity,
        summary=report.summary[:2000],
        added_columns=report.added_columns,
        removed_columns=report.removed_columns,
        type_changes=[change.to_dict() for change in report.type_changes],
    )
    db.add(event)
    db.flush()
    return event


def compare_dataset_schemas(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    baseline_dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    record: bool = False,
) -> SchemaDriftComparisonResponse:
    """Compare two datasets' stored schemas without re-reading their files."""
    ensure_owned_project(db, project_id, current_user.id)
    if dataset_id == baseline_dataset_id:
        raise BadRequestError("A dataset cannot be compared against itself.")

    current = get_dataset_model_for_project(db, project_id, dataset_id)
    baseline = get_dataset_model_for_project(db, project_id, baseline_dataset_id)

    report = detect_schema_drift(baseline.schema_json, current.schema_json)

    if record and report.has_drift:
        record_drift_event(
            db,
            project_id=project_id,
            dataset_id=current.id,
            previous_dataset_id=baseline.id,
            report=report,
        )
        db.commit()

    payload = report.to_dict()
    return SchemaDriftComparisonResponse(
        dataset_id=current.id,
        baseline_dataset_id=baseline.id,
        **payload,
    )


def list_drift_events(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    dataset_id: uuid.UUID | None = None,
    unacknowledged_only: bool = False,
    limit: int = 50,
) -> SchemaDriftEventListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(SchemaDriftEvent).where(SchemaDriftEvent.project_id == project_id)
    if dataset_id is not None:
        statement = statement.where(SchemaDriftEvent.dataset_id == dataset_id)
    if unacknowledged_only:
        statement = statement.where(SchemaDriftEvent.acknowledged.is_(False))

    rows = db.scalars(
        statement.order_by(SchemaDriftEvent.created_at.desc()).limit(min(limit, MAX_EVENT_HISTORY))
    ).all()
    return SchemaDriftEventListResponse(
        items=[SchemaDriftEventRead.model_validate(row, from_attributes=True) for row in rows]
    )


def acknowledge_drift_event(
    db: Session, project_id: uuid.UUID, event_id: uuid.UUID, current_user: UserRead
) -> SchemaDriftEventRead:
    ensure_owned_project(db, project_id, current_user.id)
    event = db.scalar(
        select(SchemaDriftEvent).where(
            SchemaDriftEvent.id == event_id, SchemaDriftEvent.project_id == project_id
        )
    )
    if event is None:
        raise NotFoundError("Schema drift event not found.")

    event.acknowledged = True
    event.acknowledged_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return SchemaDriftEventRead.model_validate(event, from_attributes=True)


def unacknowledged_drift_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(SchemaDriftEvent.id)).where(SchemaDriftEvent.acknowledged.is_(False))
        )
        or 0
    )


def breaking_drift_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(SchemaDriftEvent.id)).where(
                SchemaDriftEvent.severity == "breaking", SchemaDriftEvent.acknowledged.is_(False)
            )
        )
        or 0
    )
