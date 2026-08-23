from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_extraction.extract import run_extraction_job
from service_extraction.schemas import (
    ConnectionTestResponse,
    DiscoveredColumnsResponse,
    DiscoveredTablesResponse,
    ExtractionConnectionCreate,
    ExtractionConnectionListResponse,
    ExtractionConnectionRead,
    ExtractionConnectionUpdate,
    ExtractionJobCreate,
    ExtractionJobListResponse,
    ExtractionJobRead,
    ExtractionJobUpdate,
    ExtractionPreviewRequest,
    ExtractionPreviewResponse,
    ExtractionRunResponse,
)
from service_extraction.service import (
    create_connection,
    create_job,
    delete_connection,
    delete_job,
    discover_columns,
    discover_tables,
    list_connections,
    list_jobs,
    preview_extraction,
    reset_job_watermark,
    test_connection,
    update_connection,
    update_job,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
    settings: object,
) -> APIRouter:
    router = APIRouter(tags=["extraction"])

    # ------------------------------------------------------------- connections

    @router.get(
        "/projects/{project_id}/extraction/connections",
        response_model=ExtractionConnectionListResponse,
    )
    def get_connections(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionConnectionListResponse:
        return list_connections(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/extraction/connections",
        response_model=ExtractionConnectionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_connection(
        project_id: uuid.UUID,
        payload: ExtractionConnectionCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionConnectionRead:
        return create_connection(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/extraction/connections/{connection_id}",
        response_model=ExtractionConnectionRead,
    )
    def patch_connection(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        payload: ExtractionConnectionUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionConnectionRead:
        return update_connection(db, project_id, connection_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/extraction/connections/{connection_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_connection(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_connection(db, project_id, connection_id, current_user)

    @router.post(
        "/projects/{project_id}/extraction/connections/{connection_id}/test",
        response_model=ConnectionTestResponse,
    )
    def post_connection_test(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ConnectionTestResponse:
        return test_connection(db, project_id, connection_id, current_user)

    # --------------------------------------------------------------- discovery

    @router.get(
        "/projects/{project_id}/extraction/connections/{connection_id}/tables",
        response_model=DiscoveredTablesResponse,
    )
    def get_tables(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DiscoveredTablesResponse:
        return discover_tables(db, project_id, connection_id, current_user)

    @router.get(
        "/projects/{project_id}/extraction/connections/{connection_id}/columns",
        response_model=DiscoveredColumnsResponse,
    )
    def get_columns(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        table: str = Query(min_length=1, max_length=320),
        schema_name: str | None = Query(default=None, max_length=160),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DiscoveredColumnsResponse:
        return discover_columns(
            db, project_id, connection_id, table=table, schema=schema_name, current_user=current_user
        )

    @router.post(
        "/projects/{project_id}/extraction/connections/{connection_id}/preview",
        response_model=ExtractionPreviewResponse,
    )
    def post_preview(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        payload: ExtractionPreviewRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionPreviewResponse:
        return preview_extraction(db, project_id, connection_id, payload, current_user)

    # -------------------------------------------------------------------- jobs

    @router.get("/projects/{project_id}/extraction/jobs", response_model=ExtractionJobListResponse)
    def get_jobs(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionJobListResponse:
        return list_jobs(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/extraction/jobs",
        response_model=ExtractionJobRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_job(
        project_id: uuid.UUID,
        payload: ExtractionJobCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionJobRead:
        return create_job(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/extraction/jobs/{job_id}",
        response_model=ExtractionJobRead,
    )
    def patch_job(
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        payload: ExtractionJobUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionJobRead:
        return update_job(db, project_id, job_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/extraction/jobs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_job(
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_job(db, project_id, job_id, current_user)

    @router.post(
        "/projects/{project_id}/extraction/jobs/{job_id}/run",
        response_model=ExtractionRunResponse,
    )
    def post_job_run(
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: object = Depends(get_storage_backend),
    ) -> ExtractionRunResponse:
        return run_extraction_job(
            db,
            project_id=project_id,
            job_id=job_id,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    @router.post(
        "/projects/{project_id}/extraction/jobs/{job_id}/reset-watermark",
        response_model=ExtractionJobRead,
    )
    def post_job_reset_watermark(
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExtractionJobRead:
        return reset_job_watermark(db, project_id, job_id, current_user)

    return router
