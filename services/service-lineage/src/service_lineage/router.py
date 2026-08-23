from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_lineage.graph import DEFAULT_MAX_DEPTH
from service_lineage.schemas import (
    ColumnTraceRead,
    DatasetLineageResponse,
    ImpactRequest,
    ImpactResponse,
    LineageColumnListResponse,
)
from service_lineage.service import (
    analyse_impact,
    dataset_column_types,
    dataset_columns,
    get_dataset_lineage,
    trace_dataset_column,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["lineage"])

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/lineage",
        response_model=DatasetLineageResponse,
    )
    def read_lineage(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        depth: int = Query(DEFAULT_MAX_DEPTH, ge=1, le=6),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetLineageResponse:
        return get_dataset_lineage(db, project_id, dataset_id, current_user, max_depth=depth)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/lineage/columns",
        response_model=LineageColumnListResponse,
    )
    def read_columns(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> LineageColumnListResponse:
        return LineageColumnListResponse(
            dataset_id=dataset_id,
            columns=dataset_columns(db, project_id, dataset_id, current_user),
            types=dataset_column_types(db, project_id, dataset_id, current_user),
        )

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/lineage/columns/{column_name}",
        response_model=ColumnTraceRead,
    )
    def trace_column(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        column_name: str,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ColumnTraceRead:
        return trace_dataset_column(db, project_id, dataset_id, column_name, current_user)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/impact",
        response_model=ImpactResponse,
    )
    def impact(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: ImpactRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ImpactResponse:
        return analyse_impact(db, project_id, dataset_id, payload, current_user)

    return router
