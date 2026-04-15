from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_schedules.schemas import (
    ScheduledOperationCreate,
    ScheduledOperationListResponse,
    ScheduledOperationRead,
    ScheduledOperationUpdate,
    ScheduleToggleRequest,
    ScheduleTriggerResponse,
)
from service_schedules.service import (
    create_schedule,
    get_schedule,
    list_schedules,
    toggle_schedule,
    trigger_schedule_now,
    update_schedule,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., Any],
    settings: Any,
) -> APIRouter:
    router = APIRouter(tags=["schedules"])

    def _storage():
        return get_storage_backend()

    @router.post(
        "/projects/{project_id}/schedules",
        response_model=ScheduledOperationRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_schedule(
        project_id: uuid.UUID,
        payload: ScheduledOperationCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScheduledOperationRead:
        return create_schedule(db, project_id=project_id, payload=payload, current_user=current_user)

    @router.get("/projects/{project_id}/schedules", response_model=ScheduledOperationListResponse)
    def get_schedules(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScheduledOperationListResponse:
        return list_schedules(db, project_id=project_id, current_user=current_user)

    @router.get("/projects/{project_id}/schedules/{schedule_id}", response_model=ScheduledOperationRead)
    def get_one_schedule(
        project_id: uuid.UUID,
        schedule_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScheduledOperationRead:
        return get_schedule(db, project_id=project_id, schedule_id=schedule_id, current_user=current_user)

    @router.patch("/projects/{project_id}/schedules/{schedule_id}", response_model=ScheduledOperationRead)
    def patch_schedule(
        project_id: uuid.UUID,
        schedule_id: uuid.UUID,
        payload: ScheduledOperationUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScheduledOperationRead:
        return update_schedule(
            db, project_id=project_id, schedule_id=schedule_id, payload=payload, current_user=current_user
        )

    @router.post("/projects/{project_id}/schedules/{schedule_id}/toggle", response_model=ScheduledOperationRead)
    def post_toggle(
        project_id: uuid.UUID,
        schedule_id: uuid.UUID,
        payload: ScheduleToggleRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScheduledOperationRead:
        return toggle_schedule(
            db,
            project_id=project_id,
            schedule_id=schedule_id,
            enabled=payload.enabled,
            current_user=current_user,
        )

    @router.post("/projects/{project_id}/schedules/{schedule_id}/trigger-now", response_model=ScheduleTriggerResponse)
    def post_trigger_now(
        project_id: uuid.UUID,
        schedule_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend=Depends(_storage),
    ) -> ScheduleTriggerResponse:
        return trigger_schedule_now(
            db,
            project_id=project_id,
            schedule_id=schedule_id,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    return router
