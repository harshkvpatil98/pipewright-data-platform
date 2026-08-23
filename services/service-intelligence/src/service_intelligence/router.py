from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_intelligence.schemas import (
    DescribeRequest,
    DescribeResponse,
    DocumentationResponse,
    DuplicateRequest,
    DuplicateResponse,
    ExplainResponse,
    JoinSuggestionRequest,
    JoinSuggestionResponse,
    MaskingRequest,
    MaskingResponse,
    PiiScanResponse,
    RuleSuggestionResponse,
)
from service_intelligence.service import (
    build_masking,
    describe_to_steps,
    draft_documentation,
    explain_metric,
    find_duplicates,
    scan_pii,
    suggest_joins,
    suggest_quality_rules,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
) -> APIRouter:
    router = APIRouter(tags=["intelligence"])

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/pii", response_model=PiiScanResponse
    )
    def pii_scan(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> PiiScanResponse:
        """Columns that look like personal data, with how sure this is."""
        return scan_pii(db, project_id, dataset_id, current_user, storage)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/pii/mask",
        response_model=MaskingResponse,
    )
    def masking(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: MaskingRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MaskingResponse:
        return build_masking(db, project_id, dataset_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/join-keys",
        response_model=JoinSuggestionResponse,
    )
    def join_keys(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: JoinSuggestionRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> JoinSuggestionResponse:
        """How these two datasets join, judged by real value overlap."""
        return suggest_joins(db, project_id, dataset_id, payload, current_user, storage)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/duplicates",
        response_model=DuplicateResponse,
    )
    def duplicates(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DuplicateRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> DuplicateResponse:
        """Values that look like the same thing written differently."""
        return find_duplicates(db, project_id, dataset_id, payload, current_user, storage)

    @router.post("/projects/{project_id}/describe", response_model=DescribeResponse)
    def describe(
        project_id: uuid.UUID,
        payload: DescribeRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DescribeResponse:
        """Turn a typed request into pipeline steps.

        Phrase matching against a fixed vocabulary, which the response says so
        that nobody mistakes it for language understanding.
        """
        return describe_to_steps(db, project_id, payload, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/explain", response_model=ExplainResponse
    )
    def explain(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        metric: str = Query(default="row_count", max_length=48),
        window_days: int = Query(default=2, ge=1, le=30),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExplainResponse:
        """What else changed when this metric moved."""
        return explain_metric(
            db, project_id, dataset_id, metric, current_user, window_days=window_days
        )

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/documentation",
        response_model=DocumentationResponse,
    )
    def documentation(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DocumentationResponse:
        """A draft description, assembled from facts already recorded."""
        return draft_documentation(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/rule-suggestions",
        response_model=RuleSuggestionResponse,
    )
    def rule_suggestions(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RuleSuggestionResponse:
        """Quality rules the profile already justifies."""
        return suggest_quality_rules(db, project_id, dataset_id, current_user)

    return router
