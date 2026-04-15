from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_sources.schemas import SourceCreate, SourceListResponse, SourceRead
from service_sources.service import create_source, list_sources_by_project


def build_router(get_db: Callable[..., Session], get_current_user: Callable[..., UserRead]) -> APIRouter:
    router = APIRouter(tags=["sources"])

    @router.get("/projects/{project_id}/sources", response_model=SourceListResponse)
    def get_project_sources(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SourceListResponse:
        return list_sources_by_project(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/sources",
        response_model=SourceRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_project_source(
        project_id: uuid.UUID,
        payload: SourceCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SourceRead:
        return create_source(db, project_id, payload, current_user)

    return router
