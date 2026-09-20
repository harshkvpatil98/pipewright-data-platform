from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_destinations.bi_publish_service import publish_dataset_to_power_bi
from service_destinations.publish_schemas import (
    DatasetPublishPostgresRequest,
    DatasetPublishPostgresResponse,
    DatasetPublishPowerBiRequest,
    DatasetPublishPowerBiResponse,
    DatasetPublishTableauRequest,
    DatasetPublishTableauResponse,
)
from service_destinations.publish_service import publish_dataset_to_postgres
from service_destinations.tableau_publish_service import publish_dataset_to_tableau
from service_destinations.schemas import (
    DestinationCreate,
    DestinationListResponse,
    DestinationRead,
    DestinationTestResult,
    DestinationUpdate,
)
from service_destinations.service import (
    create_destination,
    delete_destination,
    get_destination,
    list_destinations,
    test_destination_connection,
    update_destination,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(tags=["destinations"])

    @router.get("/projects/{project_id}/destinations", response_model=DestinationListResponse)
    def get_project_destinations(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationListResponse:
        return list_destinations(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/destinations",
        response_model=DestinationRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_project_destination(
        project_id: uuid.UUID,
        payload: DestinationCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationRead:
        return create_destination(db, project_id, payload, current_user)

    @router.get("/projects/{project_id}/destinations/{destination_id}", response_model=DestinationRead)
    def get_project_destination(
        project_id: uuid.UUID,
        destination_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationRead:
        return get_destination(db, project_id, destination_id, current_user)

    @router.patch("/projects/{project_id}/destinations/{destination_id}", response_model=DestinationRead)
    def patch_project_destination(
        project_id: uuid.UUID,
        destination_id: uuid.UUID,
        payload: DestinationUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationRead:
        return update_destination(db, project_id, destination_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/destinations/{destination_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_project_destination(
        project_id: uuid.UUID,
        destination_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_destination(db, project_id, destination_id, current_user)

    @router.post(
        "/projects/{project_id}/destinations/{destination_id}/test",
        response_model=DestinationTestResult,
    )
    def post_project_destination_test(
        project_id: uuid.UUID,
        destination_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DestinationTestResult:
        return test_destination_connection(db, project_id, destination_id, current_user)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/publish/postgres",
        response_model=DatasetPublishPostgresResponse,
    )
    def post_publish_dataset_to_postgres(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DatasetPublishPostgresRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: Any = Depends(get_storage_backend),
    ) -> DatasetPublishPostgresResponse:
        return publish_dataset_to_postgres(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
        )

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/publish/power-bi",
        response_model=DatasetPublishPowerBiResponse,
    )
    def post_publish_dataset_to_power_bi(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DatasetPublishPowerBiRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: Any = Depends(get_storage_backend),
    ) -> DatasetPublishPowerBiResponse:
        return publish_dataset_to_power_bi(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
        )

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/publish/tableau",
        response_model=DatasetPublishTableauResponse,
    )
    def post_publish_dataset_to_tableau(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DatasetPublishTableauRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: Any = Depends(get_storage_backend),
    ) -> DatasetPublishTableauResponse:
        return publish_dataset_to_tableau(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
        )

    return router
