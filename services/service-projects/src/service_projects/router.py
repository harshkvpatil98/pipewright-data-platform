from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectListResponse,
    ProjectUpdate,
)
from service_projects.service import (
    create_project,
    delete_project,
    get_project_by_id,
    list_projects,
    update_project,
)


def build_router(get_db: Callable[..., Session], get_current_user: Callable[..., UserRead]) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.get("", response_model=ProjectListResponse)
    def get_projects(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ProjectListResponse:
        return list_projects(db, current_user)

    @router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
    def post_project(
        payload: ProjectCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ProjectDetail:
        return create_project(db, payload, current_user)

    @router.get("/{project_id}", response_model=ProjectDetail)
    def get_project(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ProjectDetail:
        return get_project_by_id(db, project_id, current_user)

    @router.patch("/{project_id}", response_model=ProjectDetail)
    def patch_project(
        project_id: uuid.UUID,
        payload: ProjectUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ProjectDetail:
        return update_project(db, project_id, payload, current_user)

    @router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_project(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_project(db, project_id, current_user)

    return router
