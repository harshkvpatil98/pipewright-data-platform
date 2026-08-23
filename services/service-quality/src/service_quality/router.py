from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_quality.catalog import rule_catalog
from service_quality.schemas import (
    AdHocRuleCheck,
    DataQualityEvaluationRequest,
    DataQualityEvaluationResponse,
    DataQualityResultListResponse,
    DataQualityRuleCreate,
    DataQualityRuleListResponse,
    DataQualityRuleRead,
    DataQualityRuleUpdate,
    RuleCatalogResponse,
    RuleResultRead,
)
from service_quality.drift_service import (
    acknowledge_drift_event,
    compare_dataset_schemas,
    list_drift_events,
)
from service_quality.schemas_drift import (
    SchemaDriftComparisonResponse,
    SchemaDriftEventListResponse,
    SchemaDriftEventRead,
)
from service_quality.service import (
    check_rule_ad_hoc,
    create_rule,
    delete_rule,
    evaluate_dataset,
    list_results,
    list_rules,
    update_rule,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
    settings: object,
) -> APIRouter:
    router = APIRouter(tags=["data-quality"])

    @router.get("/data-quality/rule-types", response_model=RuleCatalogResponse)
    def get_rule_catalog() -> RuleCatalogResponse:
        """Describe every supported rule type and its configuration keys."""
        return rule_catalog()

    @router.get("/projects/{project_id}/data-quality/rules", response_model=DataQualityRuleListResponse)
    def get_rules(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID | None = Query(default=None),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DataQualityRuleListResponse:
        return list_rules(db, project_id, current_user, dataset_id=dataset_id)

    @router.post(
        "/projects/{project_id}/data-quality/rules",
        response_model=DataQualityRuleRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_rule(
        project_id: uuid.UUID,
        payload: DataQualityRuleCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DataQualityRuleRead:
        return create_rule(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/data-quality/rules/{rule_id}", response_model=DataQualityRuleRead
    )
    def patch_rule(
        project_id: uuid.UUID,
        rule_id: uuid.UUID,
        payload: DataQualityRuleUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DataQualityRuleRead:
        return update_rule(db, project_id, rule_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/data-quality/rules/{rule_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_rule(
        project_id: uuid.UUID,
        rule_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_rule(db, project_id, rule_id, current_user)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/data-quality/check",
        response_model=RuleResultRead,
    )
    def post_ad_hoc_check(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: AdHocRuleCheck,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: object = Depends(get_storage_backend),
    ) -> RuleResultRead:
        return check_rule_ad_hoc(db, project_id, dataset_id, payload, current_user, storage_backend)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/data-quality/evaluate",
        response_model=DataQualityEvaluationResponse,
    )
    def post_evaluate(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DataQualityEvaluationRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: object = Depends(get_storage_backend),
    ) -> DataQualityEvaluationResponse:
        return evaluate_dataset(
            db, project_id, dataset_id, payload, current_user, storage_backend, settings
        )

    @router.get(
        "/projects/{project_id}/data-quality/results", response_model=DataQualityResultListResponse
    )
    def get_results(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DataQualityResultListResponse:
        return list_results(db, project_id, current_user, dataset_id=dataset_id, limit=limit)

    # ------------------------------------------------------------ schema drift

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/schema-drift",
        response_model=SchemaDriftComparisonResponse,
    )
    def get_schema_drift(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        baseline_dataset_id: uuid.UUID = Query(),
        record: bool = Query(default=False, description="Persist the comparison as a drift event."),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SchemaDriftComparisonResponse:
        return compare_dataset_schemas(
            db, project_id, dataset_id, baseline_dataset_id, current_user, record=record
        )

    @router.get(
        "/projects/{project_id}/schema-drift/events", response_model=SchemaDriftEventListResponse
    )
    def get_drift_events(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID | None = Query(default=None),
        unacknowledged_only: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SchemaDriftEventListResponse:
        return list_drift_events(
            db,
            project_id,
            current_user,
            dataset_id=dataset_id,
            unacknowledged_only=unacknowledged_only,
            limit=limit,
        )

    @router.post(
        "/projects/{project_id}/schema-drift/events/{event_id}/acknowledge",
        response_model=SchemaDriftEventRead,
    )
    def post_acknowledge_drift(
        project_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SchemaDriftEventRead:
        return acknowledge_drift_event(db, project_id, event_id, current_user)

    return router
