from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_governance.schemas import (
    AuditListResponse,
    ChangeRequestCreate,
    ChangeRequestDetail,
    ChangeRequestListResponse,
    ChangeRequestReview,
    CommentCreate,
    CommentListResponse,
    CommentRead,
    PromoteRequest,
    PromoteResponse,
    RestoreRequest,
    RestoreResponse,
    VersionDetail,
    VersionDiffResponse,
    VersionListResponse,
)
from service_governance.service import (
    add_comment,
    approve_change,
    diff_resource_versions,
    get_change_request,
    get_resource_version,
    list_audit_entries,
    list_change_requests,
    list_comments,
    list_resource_versions,
    promote,
    propose_change,
    reject_change,
    resolve_comment,
    restore_resource_version,
    withdraw_change,
)

_RESOURCE_PATTERN = "^(workflow|pipeline|quality_rule|extraction_job|metric)$"
_TARGET_PATTERN = "^(dataset|workflow|pipeline|run|incident|change_request|dashboard|chart)$"


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["governance"])

    # ---- version history ----

    @router.get(
        "/projects/{project_id}/history/{resource_type}/{resource_id}",
        response_model=VersionListResponse,
    )
    def read_versions(
        project_id: uuid.UUID,
        resource_id: uuid.UUID,
        resource_type: str = Path(pattern=_RESOURCE_PATTERN),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> VersionListResponse:
        return list_resource_versions(db, project_id, resource_type, resource_id, current_user)

    @router.get(
        "/projects/{project_id}/history/{resource_type}/{resource_id}/versions/{version}",
        response_model=VersionDetail,
    )
    def read_version(
        project_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        version: int,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> VersionDetail:
        return get_resource_version(
            db, project_id, resource_type, resource_id, version, current_user
        )

    @router.get(
        "/projects/{project_id}/history/{resource_type}/{resource_id}/diff",
        response_model=VersionDiffResponse,
    )
    def compare_versions(
        project_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        left: int = Query(ge=1),
        right: int = Query(ge=1),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> VersionDiffResponse:
        return diff_resource_versions(
            db, project_id, resource_type, resource_id, left, right, current_user
        )

    @router.post(
        "/projects/{project_id}/history/{resource_type}/{resource_id}/restore",
        response_model=RestoreResponse,
    )
    def restore(
        project_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        payload: RestoreRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RestoreResponse:
        return restore_resource_version(
            db, project_id, resource_type, resource_id, payload, current_user
        )

    # ---- approvals ----

    @router.get("/projects/{project_id}/changes", response_model=ChangeRequestListResponse)
    def read_changes(
        project_id: uuid.UUID,
        status_filter: str | None = Query(
            default=None, alias="status", pattern="^(open|approved|rejected|withdrawn)$"
        ),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestListResponse:
        return list_change_requests(db, project_id, current_user, status=status_filter)

    @router.post(
        "/projects/{project_id}/changes",
        response_model=ChangeRequestDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def create_change(
        project_id: uuid.UUID,
        payload: ChangeRequestCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        return propose_change(db, project_id, payload, current_user)

    @router.get(
        "/projects/{project_id}/changes/{change_id}", response_model=ChangeRequestDetail
    )
    def read_change(
        project_id: uuid.UUID,
        change_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        return get_change_request(db, project_id, change_id, current_user)

    @router.post(
        "/projects/{project_id}/changes/{change_id}/approve",
        response_model=ChangeRequestDetail,
    )
    def approve(
        project_id: uuid.UUID,
        change_id: uuid.UUID,
        payload: ChangeRequestReview,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        return approve_change(db, project_id, change_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/changes/{change_id}/reject",
        response_model=ChangeRequestDetail,
    )
    def reject(
        project_id: uuid.UUID,
        change_id: uuid.UUID,
        payload: ChangeRequestReview,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        return reject_change(db, project_id, change_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/changes/{change_id}/withdraw",
        response_model=ChangeRequestDetail,
    )
    def withdraw(
        project_id: uuid.UUID,
        change_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        return withdraw_change(db, project_id, change_id, current_user)

    # ---- environments ----

    @router.post("/projects/{project_id}/promote", response_model=PromoteResponse)
    def promote_resource_to(
        project_id: uuid.UUID,
        payload: PromoteRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PromoteResponse:
        return promote(db, project_id, payload, current_user)

    # ---- audit log ----

    @router.get("/projects/{project_id}/audit-log", response_model=AuditListResponse)
    def read_audit(
        project_id: uuid.UUID,
        outcome: str | None = Query(default=None, pattern="^(succeeded|denied|failed)$"),
        limit: int = Query(100, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AuditListResponse:
        return list_audit_entries(db, project_id, current_user, outcome=outcome, limit=limit)

    # ---- comments ----

    @router.get("/projects/{project_id}/discussion", response_model=CommentListResponse)
    def read_comments(
        project_id: uuid.UUID,
        target_id: uuid.UUID,
        target_type: str = Query(default=..., pattern=_TARGET_PATTERN),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CommentListResponse:
        return list_comments(db, project_id, target_type, target_id, current_user)

    @router.post(
        "/projects/{project_id}/discussion",
        response_model=CommentRead,
        status_code=status.HTTP_201_CREATED,
    )
    def write_comment(
        project_id: uuid.UUID,
        payload: CommentCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CommentRead:
        return add_comment(db, project_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/discussion/{comment_id}/resolve", response_model=CommentRead
    )
    def close_comment(
        project_id: uuid.UUID,
        comment_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CommentRead:
        return resolve_comment(db, project_id, comment_id, current_user)

    return router
