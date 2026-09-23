"""Cross-project operator views: all your runs, all your datasets, in one place.

The top-level /runs and /datasets routes used to redirect into whichever project
was most recent -- useful to a single-project user, useless to an operator with
forty. These compose a view across every project a person can see: recent runs
(filterable by status) and a dataset search. They live in the gateway because
answering "across all my projects" needs the project list, the run store and the
dataset store together, scoped by the same access rule /projects uses -- owner or
shared, never everything.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_pipeline_runs.models import PipelineRun
from service_projects.contracts import shared_project_ids
from service_projects.models import Project
from service_transformations.models import TransformationPipeline

MAX_LIMIT = 200


class OperatorRunRow(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    run_type: str
    status: str
    pipeline_name: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class OperatorRunsResponse(BaseModel):
    items: list[OperatorRunRow]


class OperatorDatasetRow(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    name: str
    status: str
    ingestion_status: str
    is_derived: bool
    file_type: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    created_at: str


class OperatorDatasetsResponse(BaseModel):
    items: list[OperatorDatasetRow]


def _accessible_project_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Every project this user may see: the ones they own plus the ones shared
    with them -- the same rule the project list uses, so these views never widen
    access."""
    shared = shared_project_ids(db, user_id)
    condition = Project.owner_user_id == user_id
    if shared:
        condition = or_(condition, Project.id.in_(shared))
    return list(db.scalars(select(Project.id).where(condition)).all())


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def list_recent_runs(
    db: Session,
    *,
    current_user: UserRead,
    status: str | None = None,
    limit: int = 50,
) -> OperatorRunsResponse:
    limit = max(1, min(int(limit), MAX_LIMIT))
    project_ids = _accessible_project_ids(db, current_user.id)
    if not project_ids:
        return OperatorRunsResponse(items=[])

    statement = (
        select(PipelineRun, Project.name, TransformationPipeline.name)
        .join(Project, Project.id == PipelineRun.project_id)
        .outerjoin(TransformationPipeline, TransformationPipeline.id == PipelineRun.pipeline_id)
        .where(PipelineRun.project_id.in_(project_ids))
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
    )
    if status:
        statement = statement.where(PipelineRun.status == status)

    rows = db.execute(statement).all()
    return OperatorRunsResponse(
        items=[
            OperatorRunRow(
                id=run.id,
                project_id=run.project_id,
                project_name=project_name,
                run_type=run.run_type,
                status=run.status,
                pipeline_name=pipeline_name,
                created_at=_iso(run.created_at) or "",
                started_at=_iso(run.started_at),
                finished_at=_iso(run.completed_at),
            )
            for run, project_name, pipeline_name in rows
        ]
    )


def search_datasets(
    db: Session,
    *,
    current_user: UserRead,
    query: str | None = None,
    limit: int = 50,
) -> OperatorDatasetsResponse:
    limit = max(1, min(int(limit), MAX_LIMIT))
    project_ids = _accessible_project_ids(db, current_user.id)
    if not project_ids:
        return OperatorDatasetsResponse(items=[])

    statement = (
        select(Dataset, Project.name)
        .join(Project, Project.id == Dataset.project_id)
        .where(Dataset.project_id.in_(project_ids))
        .order_by(Dataset.created_at.desc())
        .limit(limit)
    )
    if query and query.strip():
        needle = f"%{query.strip()}%"
        statement = statement.where(Dataset.name.ilike(needle))

    rows = db.execute(statement).all()
    return OperatorDatasetsResponse(
        items=[
            OperatorDatasetRow(
                id=dataset.id,
                project_id=dataset.project_id,
                project_name=project_name,
                name=dataset.name,
                status=dataset.status,
                ingestion_status=dataset.ingestion_status,
                is_derived=dataset.is_derived,
                file_type=dataset.file_type,
                row_count=dataset.row_count,
                column_count=dataset.column_count,
                created_at=_iso(dataset.created_at) or "",
            )
            for dataset, project_name in rows
        ]
    )


def build_operator_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    """Top-level, authenticated, cross-project reads. No {project_id} in the
    path -- the access rule inside each view does the scoping, not the URL."""
    router = APIRouter(tags=["operator"])

    @router.get("/runs", response_model=OperatorRunsResponse)
    def recent_runs(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OperatorRunsResponse:
        return list_recent_runs(db, current_user=current_user, status=status, limit=limit)

    @router.get("/datasets", response_model=OperatorDatasetsResponse)
    def dataset_search(
        q: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OperatorDatasetsResponse:
        return search_datasets(db, current_user=current_user, query=q, limit=limit)

    return router
