from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_observability.anomaly import DEFAULT_SENSITIVITY
from service_observability.schemas import (
    AnomalyScanResponse,
    FreshnessCheckResponse,
    FreshnessPolicyCreate,
    FreshnessPolicyListResponse,
    FreshnessPolicyRead,
    FreshnessPolicyUpdate,
    IncidentActionRequest,
    IncidentAssignRequest,
    IncidentCommentRequest,
    IncidentDetail,
    IncidentListResponse,
    MetricCaptureResponse,
    MetricHistoryResponse,
)
from service_observability.service import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    acknowledge_incident,
    assign_incident,
    capture_dataset_metrics,
    check_freshness,
    comment_on_incident,
    create_freshness_policy,
    delete_freshness_policy,
    get_incident_detail,
    get_metric_history,
    list_freshness_policies,
    list_incidents,
    reopen_incident,
    resolve_incident,
    scan_dataset_anomalies,
    update_freshness_policy,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["observability"])

    # ---- metric history ----

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/metrics",
        response_model=MetricHistoryResponse,
    )
    def read_metrics(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        metric: str | None = Query(default=None),
        column: str | None = Query(default=None),
        limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MetricHistoryResponse:
        return get_metric_history(
            db,
            project_id,
            dataset_id,
            current_user,
            metric_key=metric,
            column_name=column,
            limit=limit,
        )

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/metrics/capture",
        response_model=MetricCaptureResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def capture_metrics(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MetricCaptureResponse:
        return capture_dataset_metrics(db, project_id, dataset_id, current_user)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/anomalies",
        response_model=AnomalyScanResponse,
    )
    def read_anomalies(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        sensitivity: str = Query(DEFAULT_SENSITIVITY, pattern="^(low|medium|high)$"),
        raise_incidents: bool = Query(False),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AnomalyScanResponse:
        return scan_dataset_anomalies(
            db,
            project_id,
            dataset_id,
            current_user,
            sensitivity=sensitivity,
            open_incidents=raise_incidents,
        )

    # ---- freshness ----

    @router.get(
        "/projects/{project_id}/freshness-policies",
        response_model=FreshnessPolicyListResponse,
    )
    def read_policies(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> FreshnessPolicyListResponse:
        return list_freshness_policies(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/freshness-policies",
        response_model=FreshnessPolicyRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_policy(
        project_id: uuid.UUID,
        payload: FreshnessPolicyCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> FreshnessPolicyRead:
        return create_freshness_policy(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/freshness-policies/{policy_id}",
        response_model=FreshnessPolicyRead,
    )
    def patch_policy(
        project_id: uuid.UUID,
        policy_id: uuid.UUID,
        payload: FreshnessPolicyUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> FreshnessPolicyRead:
        return update_freshness_policy(db, project_id, policy_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/freshness-policies/{policy_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_policy(
        project_id: uuid.UUID,
        policy_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_freshness_policy(db, project_id, policy_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/projects/{project_id}/freshness/check",
        response_model=FreshnessCheckResponse,
    )
    def run_freshness_check(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> FreshnessCheckResponse:
        return check_freshness(db, project_id, current_user)

    # ---- incidents ----

    @router.get("/projects/{project_id}/incidents", response_model=IncidentListResponse)
    def read_incidents(
        project_id: uuid.UUID,
        status_filter: str | None = Query(
            default=None, alias="status", pattern="^(open|acknowledged|resolved)$"
        ),
        severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
        limit: int = Query(100, ge=1, le=500),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentListResponse:
        return list_incidents(
            db, project_id, current_user, status=status_filter, severity=severity, limit=limit
        )

    @router.get(
        "/projects/{project_id}/incidents/{incident_id}", response_model=IncidentDetail
    )
    def read_incident(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return get_incident_detail(db, project_id, incident_id, current_user)

    @router.post(
        "/projects/{project_id}/incidents/{incident_id}/acknowledge",
        response_model=IncidentDetail,
    )
    def ack(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return acknowledge_incident(db, project_id, incident_id, current_user)

    @router.post(
        "/projects/{project_id}/incidents/{incident_id}/resolve",
        response_model=IncidentDetail,
    )
    def close(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        payload: IncidentActionRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return resolve_incident(db, project_id, incident_id, payload.note, current_user)

    @router.post(
        "/projects/{project_id}/incidents/{incident_id}/reopen",
        response_model=IncidentDetail,
    )
    def open_again(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        payload: IncidentActionRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return reopen_incident(db, project_id, incident_id, payload.note, current_user)

    @router.post(
        "/projects/{project_id}/incidents/{incident_id}/assign",
        response_model=IncidentDetail,
    )
    def set_assignee(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        payload: IncidentAssignRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return assign_incident(
            db, project_id, incident_id, payload.assignee_user_id, current_user
        )

    @router.post(
        "/projects/{project_id}/incidents/{incident_id}/comments",
        response_model=IncidentDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def add_comment(
        project_id: uuid.UUID,
        incident_id: uuid.UUID,
        payload: IncidentCommentRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> IncidentDetail:
        return comment_on_incident(db, project_id, incident_id, payload, current_user)

    return router
