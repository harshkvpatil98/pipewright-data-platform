from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_destinations.bi_schemas import (
    BiConnectionMetadataResponse,
    BiIntegrationCreate,
    BiIntegrationListResponse,
    BiIntegrationRead,
    BiIntegrationUpdate,
)
from service_destinations.bi_service import (
    check_bi_connection,
    create_bi_connection,
    discover_bi_metadata,
    get_bi_connection,
    list_bi_connections,
    update_bi_connection,
)
from service_destinations.schemas import DestinationTestResult


def build_bi_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["bi-connections"])

    @router.get("/projects/{project_id}/bi-connections", response_model=BiIntegrationListResponse)
    def get_project_bi_connections(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BiIntegrationListResponse:
        return list_bi_connections(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/bi-connections",
        response_model=BiIntegrationRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_project_bi_connection(
        project_id: uuid.UUID,
        payload: BiIntegrationCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BiIntegrationRead:
        return create_bi_connection(db, project_id, payload, current_user)

    @router.get("/projects/{project_id}/bi-connections/{connection_id}", response_model=BiIntegrationRead)
    def get_project_bi_connection(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BiIntegrationRead:
        return get_bi_connection(db, project_id, connection_id, current_user)

    @router.patch("/projects/{project_id}/bi-connections/{connection_id}", response_model=BiIntegrationRead)
    def patch_project_bi_connection(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        payload: BiIntegrationUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BiIntegrationRead:
        return update_bi_connection(db, project_id, connection_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/bi-connections/{connection_id}/test",
        response_model=DestinationTestResult,
    )
    def post_project_bi_connection_test(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationTestResult:
        return check_bi_connection(db, project_id, connection_id, current_user)

    @router.get(
        "/projects/{project_id}/bi-connections/{connection_id}/metadata",
        response_model=BiConnectionMetadataResponse,
    )
    def get_project_bi_connection_metadata(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BiConnectionMetadataResponse:
        return discover_bi_metadata(db, project_id, connection_id, current_user)

    return router
