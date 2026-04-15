from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from service_auth.schemas import UserRead
from service_ingestion.contracts import read_upload_file
from service_ingestion.schemas import DatasetUploadResponse
from service_ingestion.service import ingest_project_file


def build_router(
    get_db: Callable,
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable,
    settings,
) -> APIRouter:
    router = APIRouter(tags=['ingestion'])

    @router.post(
        '/projects/{project_id}/datasets/upload',
        response_model=DatasetUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_dataset(
        project_id: uuid.UUID,
        dataset_name: str | None = Query(default=None),
        file: UploadFile = File(...),
        db = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(get_storage_backend),
    ) -> DatasetUploadResponse:
        try:
            upload = await read_upload_file(file)
            return ingest_project_file(
                db,
                project_id=project_id,
                dataset_name=dataset_name,
                upload_file=upload,
                storage_backend=storage_backend,
                settings=settings,
                current_user=current_user,
            )
        finally:
            await file.close()

    return router
