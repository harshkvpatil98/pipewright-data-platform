from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_enterprise.schemas import (
    ErasureCreate,
    ErasureListResponse,
    ErasureRead,
    LimitsResponse,
    OrganisationCreate,
    OrganisationListResponse,
    OrganisationRead,
    PolicyCreate,
    PolicyListResponse,
    PolicyPreviewResponse,
    PolicyRead,
    PolicyUpdate,
    RetentionCreate,
    RetentionListResponse,
    RetentionRead,
    RetentionRunResponse,
    SsoStatusResponse,
    UsageResponse,
)
from service_enterprise.service import (
    assign_project,
    assign_user,
    create_organisation,
    delete_organisation,
    create_policy,
    create_retention,
    delete_policy,
    limits,
    list_erasures,
    list_organisations,
    unassign_project,
    unassign_user,
    list_policies,
    list_retention,
    preview_policies,
    request_erasure,
    run_retention,
    update_policy,
    usage_report,
)
from service_enterprise.sso import saml_status
from service_enterprise.telemetry import collect, render


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
) -> APIRouter:
    router = APIRouter(tags=["enterprise"])

    # ---- organisations ----

    @router.get("/organisations", response_model=OrganisationListResponse)
    def read_organisations(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationListResponse:
        return list_organisations(db, current_user)

    @router.post(
        "/organisations",
        response_model=OrganisationRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_organisation(
        payload: OrganisationCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationRead:
        return create_organisation(db, payload, current_user)

    @router.post(
        "/organisations/{organisation_id}/users/{user_id}", response_model=OrganisationRead
    )
    def add_member(
        organisation_id: uuid.UUID,
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationRead:
        return assign_user(db, organisation_id, user_id, current_user)

    @router.post(
        "/organisations/{organisation_id}/projects/{project_id}",
        response_model=OrganisationRead,
    )
    def add_project(
        organisation_id: uuid.UUID,
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationRead:
        return assign_project(db, organisation_id, project_id, current_user)

    @router.delete(
        "/organisations/{organisation_id}/users/{user_id}",
        response_model=OrganisationRead,
    )
    def remove_member(
        organisation_id: uuid.UUID,
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationRead:
        """Revoke somebody's membership of a tenant.

        The missing half of `add_member`. Without it, joining an organisation
        was permanent and an offboarded colleague kept reaching every project
        in it.
        """
        return unassign_user(db, organisation_id, user_id, current_user)

    @router.delete(
        "/organisations/{organisation_id}/projects/{project_id}",
        response_model=OrganisationRead,
    )
    def remove_project(
        organisation_id: uuid.UUID,
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> OrganisationRead:
        return unassign_project(db, organisation_id, project_id, current_user)

    @router.delete(
        "/organisations/{organisation_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def remove_organisation(
        organisation_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_organisation(db, organisation_id, current_user)

    @router.get("/organisations/limits", response_model=LimitsResponse)
    def read_limits(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> LimitsResponse:
        return limits(db, current_user)

    # ---- security policies ----

    @router.get("/projects/{project_id}/security-policies", response_model=PolicyListResponse)
    def read_policies(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID | None = Query(default=None),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PolicyListResponse:
        return list_policies(db, project_id, current_user, dataset_id=dataset_id)

    @router.post(
        "/projects/{project_id}/security-policies",
        response_model=PolicyRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_policy(
        project_id: uuid.UUID,
        payload: PolicyCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PolicyRead:
        return create_policy(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/security-policies/{policy_id}", response_model=PolicyRead
    )
    def edit_policy(
        project_id: uuid.UUID,
        policy_id: uuid.UUID,
        payload: PolicyUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PolicyRead:
        return update_policy(db, project_id, policy_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/security-policies/{policy_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_policy(
        project_id: uuid.UUID,
        policy_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_policy(db, project_id, policy_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/security-preview",
        response_model=PolicyPreviewResponse,
    )
    def preview(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        role: str = Query(default="viewer", pattern="^(viewer|operator|editor|admin)$"),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> PolicyPreviewResponse:
        """What somebody with this role would actually see."""
        return preview_policies(db, project_id, dataset_id, role, current_user, storage)

    # ---- retention and erasure ----

    @router.get("/projects/{project_id}/retention", response_model=RetentionListResponse)
    def read_retention(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RetentionListResponse:
        return list_retention(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/retention",
        response_model=RetentionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_retention(
        project_id: uuid.UUID,
        payload: RetentionCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RetentionRead:
        return create_retention(db, project_id, payload, current_user)

    @router.post("/projects/{project_id}/retention/run", response_model=RetentionRunResponse)
    def sweep(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RetentionRunResponse:
        return run_retention(db, project_id, current_user)

    @router.get("/projects/{project_id}/erasures", response_model=ErasureListResponse)
    def read_erasures(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ErasureListResponse:
        return list_erasures(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/erasures",
        response_model=ErasureRead,
        status_code=status.HTTP_201_CREATED,
    )
    def erase(
        project_id: uuid.UUID,
        payload: ErasureCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> ErasureRead:
        """Find a person across every dataset, and redact them if asked."""
        return request_erasure(db, project_id, payload, current_user, storage)

    # ---- usage ----

    @router.get("/projects/{project_id}/usage", response_model=UsageResponse)
    def read_usage(
        project_id: uuid.UUID,
        period_days: int = Query(default=30, ge=1, le=365),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> UsageResponse:
        return usage_report(db, project_id, current_user, period_days=period_days)

    # ---- sso ----

    @router.get("/sso/status", response_model=SsoStatusResponse)
    def sso(
        _current_user: UserRead = Depends(get_current_user),
    ) -> SsoStatusResponse:
        """What single sign-on is available, and what is not."""
        from api_gateway.config import settings

        issuer = getattr(settings, "oidc_issuer", None)
        return SsoStatusResponse(
            oidc_configured=bool(issuer),
            issuer=issuer,
            saml=saml_status(),
            note=(
                "The OIDC flow is implemented to specification but has not been run "
                "against a live identity provider on this deployment."
            ),
        )

    return router


def build_metrics_router(get_db: Callable[..., Session]) -> APIRouter:
    """The scrape endpoint, mounted outside the authenticated API.

    Prometheus does not carry a bearer token, and putting metrics behind the
    login would mean nobody could watch the service that serves the login.
    Nothing here is per-person or per-row: it is counts.
    """
    router = APIRouter(tags=["telemetry"])

    @router.get("/metrics", include_in_schema=False)
    def metrics(db: Session = Depends(get_db)) -> Response:
        return Response(content=render(collect(db)), media_type="text/plain; version=0.0.4")

    return router
