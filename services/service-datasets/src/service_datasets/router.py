from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.schemas import (
    DatasetAuditSummary,
    DatasetCreate,
    DatasetDetailRead,
    DatasetListResponse,
    DatasetPreviewResponse,
    DatasetProfileResponse,
    DatasetUpdate,
    DatasetVersionListResponse,
)
from service_datasets.reporting.html_renderer import (
    build_dataset_audit_export_filename,
    render_dataset_audit_html,
)
from service_datasets.service import (
    create_dataset,
    delete_dataset,
    get_dataset_audit_summary,
    get_dataset_by_project,
    get_dataset_preview,
    get_dataset_profile,
    list_dataset_versions,
    list_datasets_by_project,
    update_dataset,
)
from shared_python.errors import BadRequestError


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable | None = None,
) -> APIRouter:
    router = APIRouter(tags=["datasets"])

    @router.get("/projects/{project_id}/datasets", response_model=DatasetListResponse)
    def get_project_datasets(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetListResponse:
        return list_datasets_by_project(db, project_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}",
        response_model=DatasetDetailRead,
    )
    def get_project_dataset(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetDetailRead:
        return get_dataset_by_project(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/versions",
        response_model=DatasetVersionListResponse,
    )
    def get_project_dataset_versions(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetVersionListResponse:
        return list_dataset_versions(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/preview",
        response_model=DatasetPreviewResponse,
    )
    def get_project_dataset_preview(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetPreviewResponse:
        return get_dataset_preview(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/profile",
        response_model=DatasetProfileResponse,
    )
    def get_project_dataset_profile(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetProfileResponse:
        return get_dataset_profile(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/audit",
        response_model=DatasetAuditSummary,
    )
    def get_project_dataset_audit(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetAuditSummary:
        return get_dataset_audit_summary(db, project_id, dataset_id, current_user)

    @router.get("/projects/{project_id}/datasets/{dataset_id}/audit/export")
    def export_project_dataset_audit(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        export_format: str = Query("html", alias="format"),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        if export_format != "html":
            raise BadRequestError("Unsupported export format. Supported: html.")
        summary = get_dataset_audit_summary(db, project_id, dataset_id, current_user)
        body = render_dataset_audit_html(summary)
        filename = build_dataset_audit_export_filename(summary)
        return Response(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post(
        "/projects/{project_id}/datasets",
        response_model=DatasetDetailRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_project_dataset(
        project_id: uuid.UUID,
        payload: DatasetCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetDetailRead:
        return create_dataset(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/datasets/{dataset_id}",
        response_model=DatasetDetailRead,
    )
    def patch_project_dataset(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DatasetUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetDetailRead:
        return update_dataset(db, project_id, dataset_id, payload, current_user)

    # The storage dependency is declared only when one was supplied. Declaring
    # it unconditionally would make `Depends(None)` a request-time failure for
    # the callers that build this router without storage -- the gateway's own
    # tests among them -- and a dataset that cannot be deleted was the bug.
    if get_storage_backend is None:

        @router.delete(
            "/projects/{project_id}/datasets/{dataset_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )
        def remove_project_dataset(
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            db: Session = Depends(get_db),
            current_user: UserRead = Depends(get_current_user),
        ) -> None:
            delete_dataset(db, project_id, dataset_id, current_user)

    else:

        @router.delete(
            "/projects/{project_id}/datasets/{dataset_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )
        def remove_project_dataset(  # type: ignore[misc]
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            db: Session = Depends(get_db),
            current_user: UserRead = Depends(get_current_user),
            storage_backend=Depends(get_storage_backend),
        ) -> None:
            delete_dataset(
                db, project_id, dataset_id, current_user, storage_backend=storage_backend
            )

    return router
