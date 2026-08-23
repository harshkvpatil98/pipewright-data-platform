from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from service_workflows.backfill import plan_backfill, queue_backfill
from service_workflows.catalog import macro_catalog
from service_workflows.queue import cancel_run, enqueue_workflow_run
from service_workflows.schemas import (
    BackfillPreviewResponse,
    BackfillRequest,
    BackfillResponse,
    MacroCatalogResponse,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowListResponse,
    RunDiffResponse,
    WorkflowRunDetail,
    WorkflowRunListResponse,
    WorkflowRunRead,
    WorkflowRunRequest,
    WorkflowUpdate,
    WorkflowValidationResponse,
)
from service_workflows.service import (
    create_workflow,
    diff_workflow_runs,
    delete_workflow,
    get_run_detail,
    get_workflow_detail,
    get_workflow_for_project,
    list_runs,
    list_workflows,
    update_workflow,
    validate_workflow,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["workflows"])

    @router.get("/projects/{project_id}/workflows", response_model=WorkflowListResponse)
    def get_workflows(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowListResponse:
        return list_workflows(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/workflows",
        response_model=WorkflowDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def post_workflow(
        project_id: uuid.UUID,
        payload: WorkflowCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowDetail:
        return create_workflow(db, project_id, payload, current_user)

    @router.get(
        "/projects/{project_id}/workflows/{workflow_id}", response_model=WorkflowDetail
    )
    def get_workflow(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowDetail:
        return get_workflow_detail(db, project_id, workflow_id, current_user)

    @router.patch(
        "/projects/{project_id}/workflows/{workflow_id}", response_model=WorkflowDetail
    )
    def patch_workflow(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        payload: WorkflowUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowDetail:
        return update_workflow(db, project_id, workflow_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/workflows/{workflow_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_workflow(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_workflow(db, project_id, workflow_id, current_user)

    @router.get(
        "/projects/{project_id}/workflows/{workflow_id}/validate",
        response_model=WorkflowValidationResponse,
    )
    def get_validation(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowValidationResponse:
        return validate_workflow(db, project_id, workflow_id, current_user)

    @router.post(
        "/projects/{project_id}/workflows/{workflow_id}/run",
        response_model=WorkflowRunRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def post_run(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        payload: WorkflowRunRequest | None = None,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowRunRead:
        """Queue a run and return immediately; a worker executes it."""
        ensure_owned_project(db, project_id, current_user.id)
        workflow = get_workflow_for_project(db, project_id, workflow_id)

        # Refuse to queue a graph that cannot run, rather than failing later.
        validation = validate_workflow(db, project_id, workflow_id, current_user)
        if not validation.valid:
            from shared_python.errors import BadRequestError

            raise BadRequestError(
                "This workflow cannot run: "
                + "; ".join(str(issue.get("message")) for issue in validation.errors)
            )

        run = enqueue_workflow_run(
            db,
            workflow=workflow,
            triggered_by_user_id=current_user.id,
            trigger="manual",
            parameters=(payload.parameters if payload else {}),
        )
        return WorkflowRunRead.model_validate(run, from_attributes=True)

    @router.get("/projects/{project_id}/workflow-runs", response_model=WorkflowRunListResponse)
    def get_runs(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowRunListResponse:
        return list_runs(db, project_id, current_user, workflow_id=workflow_id, limit=limit)

    @router.get(
        "/projects/{project_id}/workflow-runs/{run_id}", response_model=WorkflowRunDetail
    )
    def get_run(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowRunDetail:
        return get_run_detail(db, project_id, run_id, current_user)

    @router.get("/workflows/macros", response_model=MacroCatalogResponse)
    def get_macros() -> MacroCatalogResponse:
        """Macros available inside node configuration."""
        return macro_catalog()

    @router.post(
        "/projects/{project_id}/workflows/{workflow_id}/backfill/preview",
        response_model=BackfillPreviewResponse,
    )
    def post_backfill_preview(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        payload: BackfillRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BackfillPreviewResponse:
        """Show how many runs a backfill would queue, without queuing them."""
        ensure_owned_project(db, project_id, current_user.id)
        get_workflow_for_project(db, project_id, workflow_id)

        plan = plan_backfill(start=payload.start, end=payload.end, interval=payload.interval)
        return BackfillPreviewResponse(
            interval=plan.interval,
            slot_count=plan.count,
            first_slot=plan.slots[0] if plan.slots else None,
            last_slot=plan.slots[-1] if plan.slots else None,
            sample_slots=plan.slots[:5],
        )

    @router.post(
        "/projects/{project_id}/workflows/{workflow_id}/backfill",
        response_model=BackfillResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def post_backfill(
        project_id: uuid.UUID,
        workflow_id: uuid.UUID,
        payload: BackfillRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> BackfillResponse:
        ensure_owned_project(db, project_id, current_user.id)
        workflow = get_workflow_for_project(db, project_id, workflow_id)

        validation = validate_workflow(db, project_id, workflow_id, current_user)
        if not validation.valid:
            from shared_python.errors import BadRequestError

            raise BadRequestError(
                "This workflow cannot run: "
                + "; ".join(str(issue.get("message")) for issue in validation.errors)
            )

        plan = plan_backfill(start=payload.start, end=payload.end, interval=payload.interval)
        runs = queue_backfill(
            db,
            workflow=workflow,
            plan=plan,
            triggered_by_user_id=current_user.id,
            parameters=payload.parameters,
        )
        return BackfillResponse(
            interval=plan.interval,
            runs_queued=len(runs),
            run_ids=[run.id for run in runs],
            first_slot=plan.slots[0] if plan.slots else None,
            last_slot=plan.slots[-1] if plan.slots else None,
        )

    @router.post(
        "/projects/{project_id}/workflow-runs/{run_id}/cancel", response_model=WorkflowRunRead
    )
    def post_cancel(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WorkflowRunRead:
        ensure_owned_project(db, project_id, current_user.id)
        run = cancel_run(db, project_id=project_id, run_id=run_id)
        return WorkflowRunRead.model_validate(run, from_attributes=True)

    @router.get(
        "/projects/{project_id}/workflow-runs/{left_run_id}/diff/{right_run_id}",
        response_model=RunDiffResponse,
    )
    def compare_runs(
        project_id: uuid.UUID,
        left_run_id: uuid.UUID,
        right_run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RunDiffResponse:
        return diff_workflow_runs(db, project_id, left_run_id, right_run_id, current_user)

    return router
