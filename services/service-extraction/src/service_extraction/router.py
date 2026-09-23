from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Response, APIRouter, Depends, Query, status, Request
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_extraction.extract import run_extraction_job
from service_extraction.streams import (
    create_source,
    delete_source,
    get_source,
    list_events,
    list_sources,
    materialise_source,
    poll_source,
    receive_webhook,
)
from service_extraction.schemas import (
    StreamEventListResponse,
    StreamEventRead,
    StreamMaterialiseResponse,
    StreamPollResponse,
    StreamSourceCreate,
    StreamSourceCreated,
    StreamSourceListResponse,
    StreamSourceRead,
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

    # ------------------------------------------------------- stream sources

    @router.get("/projects/{project_id}/streams", response_model=StreamSourceListResponse)
    def read_streams(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> StreamSourceListResponse:
        return list_sources(db, project_id, current_user)

    @router.post("/projects/{project_id}/streams", response_model=StreamSourceCreated, status_code=status.HTTP_201_CREATED)
    def add_stream(
        project_id: uuid.UUID,
        payload: StreamSourceCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> StreamSourceCreated:
        """A webhook's token comes back in this response and never again."""
        return create_source(db, project_id, payload, current_user)

    @router.get("/projects/{project_id}/streams/{source_id}", response_model=StreamSourceRead)
    def read_stream(
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> StreamSourceRead:
        return get_source(db, project_id, source_id, current_user)

    @router.delete("/projects/{project_id}/streams/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_stream(
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_source(db, project_id, source_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/projects/{project_id}/streams/{source_id}/events", response_model=StreamEventListResponse)
    def read_stream_events(
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        limit: int = Query(default=50, ge=1, le=500),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> StreamEventListResponse:
        return list_events(db, project_id, source_id, current_user, limit=limit)

    @router.post("/projects/{project_id}/streams/{source_id}/poll", response_model=StreamPollResponse)
    def poll_stream(
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> StreamPollResponse:
        """Read the next batch of changes from the replication slot now
        (operator: it is running the job by hand)."""
        return poll_source(db, project_id, source_id, current_user)

    @router.post("/projects/{project_id}/streams/{source_id}/materialise", response_model=StreamMaterialiseResponse)
    def materialise_stream(
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend=Depends(get_storage_backend),
    ) -> StreamMaterialiseResponse:
        """Write every event so far as a new immutable dataset version."""
        return materialise_source(db, project_id, source_id, current_user, storage_backend, settings)

    return router


def build_public_router(get_db: Callable[..., Session]) -> APIRouter:
    """The inbound webhook endpoint. No user: the token in the path IS the
    authorisation, checked against a hash. Top-level (no project in the path)
    so the project guard has nothing to gate; an unknown token is a 404."""
    router = APIRouter(tags=["hooks"])

    @router.post("/hooks/{token}", response_model=StreamEventRead, status_code=status.HTTP_202_ACCEPTED)
    async def receive(token: str, request: Request, db: Session = Depends(get_db)) -> StreamEventRead:
        body = await request.body()
        return receive_webhook(
            db, token=token, body=body, content_type=request.headers.get("content-type"),
            headers={k: v for k, v in request.headers.items()},
        )

    return router
