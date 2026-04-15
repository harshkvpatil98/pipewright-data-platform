from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_pipeline_runs.schemas import PipelineRunListResponse, PipelineRunRead, RunAuditSummary
from service_pipeline_runs.reporting.html_renderer import (
    build_run_audit_export_filename,
    render_run_audit_html,
)
from service_pipeline_runs.service import (
    create_sample_pipeline_run,
    get_pipeline_run,
    get_run_audit_summary,
    list_pipeline_runs,
)
from shared_python.errors import BadRequestError


def build_router(get_db: Callable[..., Session], get_current_user: Callable[..., UserRead]) -> APIRouter:
    router = APIRouter(tags=["pipeline-runs"])

    @router.post(
        "/projects/{project_id}/runs/sample",
        response_model=PipelineRunRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_sample_run(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PipelineRunRead:
        return create_sample_pipeline_run(db, project_id, current_user)

    @router.get("/projects/{project_id}/runs", response_model=PipelineRunListResponse)
    def get_project_runs(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PipelineRunListResponse:
        return list_pipeline_runs(db, project_id, current_user)

    @router.get("/projects/{project_id}/runs/{run_id}", response_model=PipelineRunRead)
    def get_project_run(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PipelineRunRead:
        return get_pipeline_run(db, project_id, run_id, current_user)

    @router.get(
        "/projects/{project_id}/runs/{run_id}/audit",
        response_model=RunAuditSummary,
    )
    def get_project_run_audit(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RunAuditSummary:
        return get_run_audit_summary(db, project_id, run_id, current_user)

    @router.get("/projects/{project_id}/runs/{run_id}/audit/export")
    def export_project_run_audit(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        export_format: str = Query("html", alias="format"),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        if export_format != "html":
            raise BadRequestError("Unsupported export format. Supported: html.")
        summary = get_run_audit_summary(db, project_id, run_id, current_user)
        body = render_run_audit_html(summary)
        filename = build_run_audit_export_filename(summary)
        return Response(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
