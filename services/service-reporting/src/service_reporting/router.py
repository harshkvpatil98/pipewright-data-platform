from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_reporting.schemas import (
    AnnotationRead,
    AnnotationUpdate,
    CatalogSearchResponse,
    ChartCatalogResponse,
    ChartCreate,
    ChartDataResponse,
    ChartListResponse,
    ChartPreviewRequest,
    ChartRead,
    ChartUpdate,
    ChartWithData,
    DashboardCreate,
    DashboardDetail,
    DashboardListResponse,
    DashboardRead,
    DashboardUpdate,
    DatasetTermLink,
    DeliveryListResponse,
    PivotRequest,
    PivotResponse,
    PublicDashboardView,
    ReportCreate,
    ReportListResponse,
    ReportRead,
    ReportUpdate,
    TermCreate,
    TermListResponse,
    TermRead,
    TermUpdate,
)
from service_reporting.service import (
    chart_catalog,
    create_chart,
    create_dashboard,
    create_report,
    create_term,
    delete_chart,
    delete_dashboard,
    delete_report,
    delete_term,
    get_annotation,
    get_chart_with_data,
    get_dashboard,
    get_shared_dashboard,
    list_charts,
    list_dashboards,
    list_deliveries,
    list_reports,
    link_term_to_dataset,
    list_dataset_terms,
    list_terms,
    preview_chart,
    run_pivot,
    run_report,
    search_catalog,
    share_dashboard,
    unshare_dashboard,
    unlink_term_from_dataset,
    update_annotation,
    update_chart,
    update_dashboard,
    update_report,
    update_term,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
) -> APIRouter:
    router = APIRouter(tags=["reporting"])

    # ---- chart building ----

    @router.get("/charts/types", response_model=ChartCatalogResponse)
    def types(_user: UserRead = Depends(get_current_user)) -> ChartCatalogResponse:
        return chart_catalog()

    @router.post(
        "/projects/{project_id}/charts/preview", response_model=ChartDataResponse
    )
    def preview(
        project_id: uuid.UUID,
        payload: ChartPreviewRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> ChartDataResponse:
        return preview_chart(db, project_id, payload, current_user, storage)

    @router.get("/projects/{project_id}/charts", response_model=ChartListResponse)
    def read_charts(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChartListResponse:
        return list_charts(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/charts",
        response_model=ChartRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_chart(
        project_id: uuid.UUID,
        payload: ChartCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChartRead:
        return create_chart(db, project_id, payload, current_user)

    @router.get("/projects/{project_id}/charts/{chart_id}", response_model=ChartWithData)
    def read_chart(
        project_id: uuid.UUID,
        chart_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> ChartWithData:
        return get_chart_with_data(db, project_id, chart_id, current_user, storage)

    @router.patch("/projects/{project_id}/charts/{chart_id}", response_model=ChartRead)
    def edit_chart(
        project_id: uuid.UUID,
        chart_id: uuid.UUID,
        payload: ChartUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChartRead:
        return update_chart(db, project_id, chart_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/charts/{chart_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def remove_chart(
        project_id: uuid.UUID,
        chart_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_chart(db, project_id, chart_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ---- pivot ----

    @router.post("/projects/{project_id}/pivot", response_model=PivotResponse)
    def pivot_table(
        project_id: uuid.UUID,
        payload: PivotRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> PivotResponse:
        return run_pivot(db, project_id, payload, current_user, storage)

    # ---- dashboards ----

    @router.get("/projects/{project_id}/dashboards", response_model=DashboardListResponse)
    def read_dashboards(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardListResponse:
        return list_dashboards(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/dashboards",
        response_model=DashboardDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def add_dashboard(
        project_id: uuid.UUID,
        payload: DashboardCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardDetail:
        return create_dashboard(db, project_id, payload, current_user)

    @router.get(
        "/projects/{project_id}/dashboards/{dashboard_id}", response_model=DashboardDetail
    )
    def read_dashboard(
        project_id: uuid.UUID,
        dashboard_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardDetail:
        return get_dashboard(db, project_id, dashboard_id, current_user)

    @router.patch(
        "/projects/{project_id}/dashboards/{dashboard_id}", response_model=DashboardDetail
    )
    def edit_dashboard(
        project_id: uuid.UUID,
        dashboard_id: uuid.UUID,
        payload: DashboardUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardDetail:
        return update_dashboard(db, project_id, dashboard_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/dashboards/{dashboard_id}/share", response_model=DashboardRead
    )
    def share(
        project_id: uuid.UUID,
        dashboard_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardRead:
        return share_dashboard(db, project_id, dashboard_id, current_user)

    @router.delete(
        "/projects/{project_id}/dashboards/{dashboard_id}/share", response_model=DashboardRead
    )
    def unshare(
        project_id: uuid.UUID,
        dashboard_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DashboardRead:
        return unshare_dashboard(db, project_id, dashboard_id, current_user)

    @router.delete(
        "/projects/{project_id}/dashboards/{dashboard_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_dashboard(
        project_id: uuid.UUID,
        dashboard_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_dashboard(db, project_id, dashboard_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ---- scheduled reports ----

    @router.get("/projects/{project_id}/reports", response_model=ReportListResponse)
    def read_reports(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ReportListResponse:
        return list_reports(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/reports",
        response_model=ReportRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_report(
        project_id: uuid.UUID,
        payload: ReportCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ReportRead:
        return create_report(db, project_id, payload, current_user)

    @router.patch("/projects/{project_id}/reports/{report_id}", response_model=ReportRead)
    def edit_report(
        project_id: uuid.UUID,
        report_id: uuid.UUID,
        payload: ReportUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ReportRead:
        return update_report(db, project_id, report_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def remove_report(
        project_id: uuid.UUID,
        report_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_report(db, project_id, report_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/projects/{project_id}/reports/{report_id}/deliveries",
        response_model=DeliveryListResponse,
    )
    def deliveries(
        project_id: uuid.UUID,
        report_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DeliveryListResponse:
        return list_deliveries(db, project_id, report_id, current_user)

    @router.post("/projects/{project_id}/reports/{report_id}/run")
    def generate(
        project_id: uuid.UUID,
        report_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage=Depends(get_storage_backend),
    ) -> Response:
        """Generate the file now and hand it straight back."""
        content, filename, media_type, _delivery = run_report(
            db, project_id, report_id, current_user, storage
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ---- catalog ----

    @router.get("/projects/{project_id}/catalog", response_model=CatalogSearchResponse)
    def catalog(
        project_id: uuid.UUID,
        q: str = Query(default="", max_length=200),
        certified_only: bool = Query(default=False),
        tag: str | None = Query(default=None, max_length=60),
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CatalogSearchResponse:
        return search_catalog(
            db,
            project_id,
            current_user,
            query=q,
            certified_only=certified_only,
            tag=tag,
            limit=limit,
        )

    @router.get(
        "/projects/{project_id}/catalog/{dataset_id}", response_model=AnnotationRead
    )
    def read_annotation(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AnnotationRead:
        return get_annotation(db, project_id, dataset_id, current_user)

    @router.patch(
        "/projects/{project_id}/catalog/{dataset_id}", response_model=AnnotationRead
    )
    def edit_annotation(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: AnnotationUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AnnotationRead:
        return update_annotation(db, project_id, dataset_id, payload, current_user)

    # ---- glossary terms linked to a dataset (from the dataset's side) ----

    @router.get(
        "/projects/{project_id}/datasets/{dataset_id}/glossary-terms",
        response_model=TermListResponse,
    )
    def dataset_terms(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermListResponse:
        return list_dataset_terms(db, project_id, dataset_id, current_user)

    @router.post(
        "/projects/{project_id}/datasets/{dataset_id}/glossary-terms",
        response_model=TermRead,
    )
    def link_dataset_term(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: DatasetTermLink,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermRead:
        return link_term_to_dataset(
            db, project_id, dataset_id, payload.term_id, payload.column, current_user
        )

    @router.delete(
        "/projects/{project_id}/datasets/{dataset_id}/glossary-terms/{term_id}",
        response_model=TermRead,
    )
    def unlink_dataset_term(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        term_id: uuid.UUID,
        column: str = Query(...),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermRead:
        return unlink_term_from_dataset(db, project_id, dataset_id, term_id, column, current_user)

    # ---- glossary ----

    @router.get("/projects/{project_id}/glossary", response_model=TermListResponse)
    def read_terms(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermListResponse:
        return list_terms(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/glossary",
        response_model=TermRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_term(
        project_id: uuid.UUID,
        payload: TermCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermRead:
        return create_term(db, project_id, payload, current_user)

    @router.patch("/projects/{project_id}/glossary/{term_id}", response_model=TermRead)
    def edit_term(
        project_id: uuid.UUID,
        term_id: uuid.UUID,
        payload: TermUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TermRead:
        return update_term(db, project_id, term_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def remove_term(
        project_id: uuid.UUID,
        term_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        delete_term(db, project_id, term_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def build_public_router(
    get_db: Callable[..., Session],
    get_storage_backend: Callable[..., object],
) -> APIRouter:
    """Unauthenticated, read-only access to a shared dashboard by its token.

    Deliberately its own router with no `current_user` dependency and no
    `{project_id}` in the path -- so the project guard has nothing to gate and
    the route is genuinely public. The token is the only key; revocation is
    immediate because unshare nulls it.
    """
    router = APIRouter(tags=["public"])

    @router.get("/public/dashboards/{token}", response_model=PublicDashboardView)
    def shared_dashboard(
        token: str,
        db: Session = Depends(get_db),
        storage_backend=Depends(get_storage_backend),
    ) -> PublicDashboardView:
        return get_shared_dashboard(db, token=token, storage_backend=storage_backend)

    return router
