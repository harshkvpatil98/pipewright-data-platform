"""Charts, dashboards, pivots, reports, the catalog, and the glossary."""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from shared_python.errors import ApplicationError, BadRequestError, NotFoundError
from shared_python.logging import get_logger

from service_reporting.aggregation import (
    AGGREGATIONS,
    FILTER_OPERATORS,
    Filter,
    Measure,
    Query,
    pivot,
    run_query,
)
from service_reporting.catalog import SearchableDataset, search, slugify
from service_reporting.charts import (
    CHART_TYPES,
    ChartData,
    kpi_with_period_delta,
    to_chart_data,
    validate_chart,
)
from service_reporting.exports import export
from service_reporting.models import (
    CatalogAnnotation,
    Dashboard,
    DashboardTile,
    GlossaryTerm,
    ReportDelivery,
    SavedChart,
    ScheduledReport,
)
from service_reporting.schemas import (
    DashboardDataRequest,
    DashboardDataResponse,
    DashboardTileData,
    AnnotationRead,
    CatalogSearchResponse,
    AnnotationUpdate,
    ChartCatalogResponse,
    ChartCreate,
    ChartDataResponse,
    ChartListResponse,
    ChartPreviewRequest,
    ChartRead,
    ChartTypeRead,
    ChartUpdate,
    ChartWithData,
    DashboardCreate,
    DashboardDetail,
    PublicChartTile,
    PublicDashboardView,
    DashboardListResponse,
    DashboardRead,
    DashboardUpdate,
    DeliveryListResponse,
    DeliveryRead,
    FilterInput,
    GlossaryBinding,
    PivotRequest,
    PivotResponse,
    QueryInput,
    ReportCreate,
    ReportListResponse,
    ReportRead,
    ReportUpdate,
    TermCreate,
    TermListResponse,
    TermRead,
    TermUpdate,
    TileRead,
)

logger = get_logger(__name__)

# A chart reads the whole dataset to aggregate it, so there has to be a ceiling.
MAX_SOURCE_ROWS = 500_000


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _get_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def _load_frame(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, storage_backend) -> pd.DataFrame:
    from service_ingestion.parsers import parse_tabular_file

    dataset = _get_dataset(db, project_id, dataset_id)
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError(f"'{dataset.name}' has no stored file to read.")

    try:
        payload = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise BadRequestError(f"The stored file for '{dataset.name}' is missing.") from exc

    frame = parse_tabular_file(file_bytes=payload, file_type=dataset.file_type).dataframe
    if len(frame) > MAX_SOURCE_ROWS:
        raise BadRequestError(
            f"'{dataset.name}' has {len(frame):,} rows, above the {MAX_SOURCE_ROWS:,} "
            "limit for charting. Aggregate it in a pipeline first."
        )
    return frame


def _to_query(payload: QueryInput) -> Query:
    return Query(
        dimensions=list(payload.dimensions),
        measures=[
            Measure(column=m.column, aggregation=m.aggregation, label=m.label)
            for m in payload.measures
        ],
        filters=[Filter(column=f.column, operator=f.operator, value=f.value) for f in payload.filters],
        sort_by=payload.sort_by,
        descending=payload.descending,
        limit=payload.limit,
    )


def _from_query(stored: dict[str, Any]) -> QueryInput:
    return QueryInput.model_validate(stored or {})


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def chart_catalog() -> ChartCatalogResponse:
    return ChartCatalogResponse(
        items=[ChartTypeRead(**chart.to_dict()) for chart in CHART_TYPES],
        aggregations=sorted(AGGREGATIONS),
        filter_operators=list(FILTER_OPERATORS),
    )


def _compute_chart(
    chart_type: str, query: Query, frame: pd.DataFrame, options: dict[str, Any] | None
) -> ChartData:
    """One place that turns a frame into chart data, for the builder preview,
    a saved chart, a dashboard tile and the public share alike -- so all four
    agree, KPI comparison included."""
    compare = (options or {}).get("compare") if isinstance(options, dict) else None
    if chart_type == "kpi" and isinstance(compare, dict) and compare.get("date_column"):
        data, warnings = kpi_with_period_delta(frame, query, compare, run=run_query)
        data.warnings = [*warnings, *data.warnings]
        return data
    return to_chart_data(chart_type, query, run_query(frame, query))


def preview_chart(
    db: Session,
    project_id: uuid.UUID,
    payload: ChartPreviewRequest,
    current_user: UserRead,
    storage_backend,
) -> ChartDataResponse:
    """Compute a chart without saving it, so the builder is interactive."""
    ensure_owned_project(db, project_id, current_user.id)
    query = _to_query(payload.query)
    warnings = validate_chart(payload.chart_type, query)

    frame = _load_frame(db, project_id, payload.dataset_id, storage_backend)
    data = _compute_chart(payload.chart_type, query, frame, payload.options)
    data.warnings = [*warnings, *data.warnings]
    return ChartDataResponse(**data.to_dict())


def _chart_read(chart: SavedChart, dataset_name: str | None) -> ChartRead:
    return ChartRead(
        id=chart.id,
        project_id=chart.project_id,
        dataset_id=chart.dataset_id,
        dataset_name=dataset_name,
        name=chart.name,
        description=chart.description,
        chart_type=chart.chart_type,
        query=_from_query(chart.query_json),
        options=chart.options_json,
        created_at=chart.created_at,
        updated_at=chart.updated_at,
    )


def create_chart(
    db: Session, project_id: uuid.UUID, payload: ChartCreate, current_user: UserRead
) -> ChartRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, payload.dataset_id)
    validate_chart(payload.chart_type, _to_query(payload.query))

    chart = SavedChart(
        project_id=project_id,
        dataset_id=payload.dataset_id,
        name=payload.name.strip(),
        description=payload.description,
        chart_type=payload.chart_type,
        query_json=payload.query.model_dump(mode="json"),
        options_json=payload.options,
        created_by_user_id=current_user.id,
    )
    db.add(chart)
    db.commit()
    db.refresh(chart)
    return _chart_read(chart, dataset.name)


def _get_chart(db: Session, project_id: uuid.UUID, chart_id: uuid.UUID) -> SavedChart:
    chart = db.scalar(
        select(SavedChart).where(SavedChart.id == chart_id, SavedChart.project_id == project_id)
    )
    if chart is None:
        raise NotFoundError("Chart not found.")
    return chart


def update_chart(
    db: Session,
    project_id: uuid.UUID,
    chart_id: uuid.UUID,
    payload: ChartUpdate,
    current_user: UserRead,
) -> ChartRead:
    ensure_owned_project(db, project_id, current_user.id)
    chart = _get_chart(db, project_id, chart_id)

    if payload.name is not None:
        chart.name = payload.name.strip()
    if payload.description is not None:
        chart.description = payload.description
    if payload.chart_type is not None:
        chart.chart_type = payload.chart_type
    if payload.query is not None:
        chart.query_json = payload.query.model_dump(mode="json")
    if payload.options is not None:
        chart.options_json = payload.options

    validate_chart(chart.chart_type, _to_query(_from_query(chart.query_json)))
    db.commit()
    db.refresh(chart)
    return _chart_read(chart, _dataset_names(db, [chart.dataset_id]).get(chart.dataset_id))


def list_charts(db: Session, project_id: uuid.UUID, current_user: UserRead) -> ChartListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    charts = list(
        db.scalars(
            select(SavedChart)
            .where(SavedChart.project_id == project_id)
            .order_by(SavedChart.updated_at.desc())
        ).all()
    )
    names = _dataset_names(db, [chart.dataset_id for chart in charts])
    return ChartListResponse(
        items=[_chart_read(chart, names.get(chart.dataset_id)) for chart in charts]
    )


def get_chart_with_data(
    db: Session,
    project_id: uuid.UUID,
    chart_id: uuid.UUID,
    current_user: UserRead,
    storage_backend,
    *,
    extra_filters: list[FilterInput] | None = None,
) -> ChartWithData:
    ensure_owned_project(db, project_id, current_user.id)
    chart = _get_chart(db, project_id, chart_id)

    stored = _from_query(chart.query_json)
    if extra_filters:
        stored = stored.model_copy(update={"filters": [*stored.filters, *extra_filters]})

    query = _to_query(stored)
    frame = _load_frame(db, project_id, chart.dataset_id, storage_backend)
    data = _compute_chart(chart.chart_type, query, frame, chart.options_json)

    names = _dataset_names(db, [chart.dataset_id])
    return ChartWithData(
        **_chart_read(chart, names.get(chart.dataset_id)).model_dump(),
        data=ChartDataResponse(**data.to_dict()),
    )


def delete_chart(
    db: Session, project_id: uuid.UUID, chart_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    db.delete(_get_chart(db, project_id, chart_id))
    db.commit()


def _dataset_names(db: Session, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    unique = [item for item in dict.fromkeys(dataset_ids) if item]
    if not unique:
        return {}
    rows = db.execute(select(Dataset.id, Dataset.name).where(Dataset.id.in_(unique))).all()
    return {row[0]: row[1] for row in rows}


# --------------------------------------------------------------------------
# Pivot
# --------------------------------------------------------------------------


def run_pivot(
    db: Session,
    project_id: uuid.UUID,
    payload: PivotRequest,
    current_user: UserRead,
    storage_backend,
) -> PivotResponse:
    """An ad-hoc question, with no pipeline in the way."""
    ensure_owned_project(db, project_id, current_user.id)
    frame = _load_frame(db, project_id, payload.dataset_id, storage_backend)

    result = pivot(
        frame,
        rows=list(payload.rows),
        columns=list(payload.columns),
        measure=Measure(
            column=payload.measure.column,
            aggregation=payload.measure.aggregation,
            label=payload.measure.label,
        ),
        filters=[
            Filter(column=f.column, operator=f.operator, value=f.value) for f in payload.filters
        ],
    )
    return PivotResponse(
        columns=[str(column) for column in result.frame.columns],
        rows=_records(result.frame),
        row_count=result.row_count,
        warnings=result.warnings,
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain JSON, with pandas' own null and numeric types removed."""
    import math

    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            if hasattr(value, "item"):
                value = value.item()
            if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
                cleaned[str(key)] = None
            elif isinstance(value, (str, int, float, bool)):
                cleaned[str(key)] = value
            else:
                cleaned[str(key)] = str(value)
        records.append(cleaned)
    return records


# --------------------------------------------------------------------------
# Dashboards
# --------------------------------------------------------------------------


def _dashboard_read(dashboard: Dashboard, tile_count: int) -> DashboardRead:
    return DashboardRead(
        id=dashboard.id,
        project_id=dashboard.project_id,
        name=dashboard.name,
        description=dashboard.description,
        tile_count=tile_count,
        share_token=dashboard.share_token,
        shared_at=dashboard.shared_at,
        refresh_seconds=dashboard.refresh_seconds,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def create_dashboard(
    db: Session, project_id: uuid.UUID, payload: DashboardCreate, current_user: UserRead
) -> DashboardDetail:
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = Dashboard(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description,
        filters_json=[item.model_dump(mode="json") for item in payload.filters] or None,
        refresh_seconds=payload.refresh_seconds,
        created_by_user_id=current_user.id,
    )
    db.add(dashboard)
    db.flush()
    _replace_tiles(db, project_id, dashboard, payload.tiles)
    db.commit()
    return get_dashboard(db, project_id, dashboard.id, current_user)


def _replace_tiles(db: Session, project_id: uuid.UUID, dashboard: Dashboard, tiles) -> None:
    for existing in db.scalars(
        select(DashboardTile).where(DashboardTile.dashboard_id == dashboard.id)
    ).all():
        db.delete(existing)
    db.flush()

    for index, tile in enumerate(tiles or []):
        if tile.kind == "chart":
            # Checked rather than trusted: a tile pointing at another project's
            # chart would leak it to everyone who can see this dashboard.
            _get_chart(db, project_id, tile.chart_id)
        db.add(
            DashboardTile(
                dashboard_id=dashboard.id,
                kind=tile.kind,
                chart_id=tile.chart_id if tile.kind == "chart" else None,
                title=(tile.title or None) if tile.kind == "text" else None,
                body=(tile.body or None) if tile.kind == "text" else None,
                position=index if tile.position is None else tile.position,
                width=tile.width,
                height=tile.height,
            )
        )
    db.flush()


def _dashboard_tiles(db: Session, dashboard: Dashboard) -> tuple[list[DashboardTile], dict]:
    tiles = list(
        db.scalars(
            select(DashboardTile)
            .where(DashboardTile.dashboard_id == dashboard.id)
            .order_by(DashboardTile.position)
        ).all()
    )
    chart_ids = [tile.chart_id for tile in tiles if tile.chart_id is not None]
    charts = {
        chart.id: chart
        for chart in db.scalars(
            select(SavedChart).where(SavedChart.id.in_(chart_ids or [uuid.uuid4()]))
        ).all()
    }
    return tiles, charts


def get_dashboard(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, current_user: UserRead
) -> DashboardDetail:
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = _get_dashboard(db, project_id, dashboard_id)

    tiles, charts = _dashboard_tiles(db, dashboard)
    names = _dataset_names(db, [chart.dataset_id for chart in charts.values()])

    reads: list[TileRead] = []
    for tile in tiles:
        if tile.kind == "text":
            reads.append(
                TileRead(
                    id=tile.id, kind="text", chart_id=None, title=tile.title, body=tile.body,
                    position=tile.position, width=tile.width, height=tile.height, chart=None,
                )
            )
            continue
        chart = charts.get(tile.chart_id)
        if chart is None:
            continue
        reads.append(
            TileRead(
                id=tile.id,
                kind="chart",
                chart_id=tile.chart_id,
                position=tile.position,
                width=tile.width,
                height=tile.height,
                chart=_chart_read(chart, names.get(chart.dataset_id)),
            )
        )

    return DashboardDetail(
        **_dashboard_read(dashboard, len(tiles)).model_dump(),
        tiles=reads,
        filters=[FilterInput.model_validate(item) for item in (dashboard.filters_json or [])],
    )


def compute_dashboard_data(
    db: Session,
    project_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    payload: DashboardDataRequest,
    current_user: UserRead,
    storage_backend,
) -> DashboardDataResponse:
    """Every tile's data in one round trip, with the dashboard's global filters
    applied to each chart's own query -- or an ad-hoc set replacing them for
    this computation only. A read (POST because filters ride in the body;
    `preview`-style, it stores nothing)."""
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = _get_dashboard(db, project_id, dashboard_id)
    tiles, charts = _dashboard_tiles(db, dashboard)
    filters = (
        list(payload.filters)
        if payload.filters is not None
        else [FilterInput.model_validate(item) for item in (dashboard.filters_json or [])]
    )
    frames: dict[uuid.UUID, pd.DataFrame] = {}

    out: list[DashboardTileData] = []
    for tile in tiles:
        base = dict(tile_id=tile.id, position=tile.position, width=tile.width, height=tile.height)
        if tile.kind == "text":
            out.append(DashboardTileData(kind="text", title=tile.title, body=tile.body, **base))
            continue
        chart = charts.get(tile.chart_id)
        if chart is None:
            out.append(DashboardTileData(kind="chart", error="This chart no longer exists.", **base))
            continue
        try:
            stored = _from_query(chart.query_json)
            if filters:
                stored = stored.model_copy(update={"filters": [*stored.filters, *filters]})
            if chart.dataset_id not in frames:
                frames[chart.dataset_id] = _load_frame(db, project_id, chart.dataset_id, storage_backend)
            data = _compute_chart(chart.chart_type, _to_query(stored), frames[chart.dataset_id], chart.options_json)
            out.append(
                DashboardTileData(
                    kind="chart", chart_id=chart.id, chart_name=chart.name, chart_type=chart.chart_type,
                    data=ChartDataResponse(**data.to_dict()), **base,
                )
            )
        except ApplicationError as exc:
            out.append(
                DashboardTileData(
                    kind="chart", chart_id=chart.id, chart_name=chart.name, chart_type=chart.chart_type,
                    error=str(exc.detail), **base,
                )
            )
        except Exception:  # noqa: BLE001 - one bad tile must not fail the page
            logger.exception("dashboard_tile_failed chart_id=%s", chart.id)
            out.append(
                DashboardTileData(
                    kind="chart", chart_id=chart.id, chart_name=chart.name, chart_type=chart.chart_type,
                    error="This chart could not be computed.", **base,
                )
            )

    return DashboardDataResponse(
        dashboard_id=dashboard.id,
        computed_at=datetime.now(UTC),
        filters_applied=filters,
        tiles=out,
    )


def _get_dashboard(db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = db.scalar(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    if dashboard is None:
        raise NotFoundError("Dashboard not found.")
    return dashboard


def update_dashboard(
    db: Session,
    project_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    current_user: UserRead,
) -> DashboardDetail:
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = _get_dashboard(db, project_id, dashboard_id)

    if payload.name is not None:
        dashboard.name = payload.name.strip()
    if payload.description is not None:
        dashboard.description = payload.description
    if payload.filters is not None:
        dashboard.filters_json = [item.model_dump(mode="json") for item in payload.filters] or None
    if "refresh_seconds" in payload.model_fields_set:
        dashboard.refresh_seconds = payload.refresh_seconds
    if payload.tiles is not None:
        _replace_tiles(db, project_id, dashboard, payload.tiles)

    db.commit()
    return get_dashboard(db, project_id, dashboard_id, current_user)


def list_dashboards(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> DashboardListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dashboards = list(
        db.scalars(
            select(Dashboard)
            .where(Dashboard.project_id == project_id)
            .order_by(Dashboard.updated_at.desc())
        ).all()
    )
    counts = dict(
        db.execute(
            select(DashboardTile.dashboard_id, func.count(DashboardTile.id)).group_by(
                DashboardTile.dashboard_id
            )
        ).all()
    )
    return DashboardListResponse(
        items=[
            _dashboard_read(dashboard, int(counts.get(dashboard.id, 0)))
            for dashboard in dashboards
        ]
    )


def share_dashboard(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, current_user: UserRead
) -> DashboardRead:
    """Grant a link that works without signing in.

    The token is generated on request rather than at creation: a dashboard that
    is shareable by default is a dashboard that is shared by accident.
    """
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = _get_dashboard(db, project_id, dashboard_id)
    if dashboard.share_token is None:
        dashboard.share_token = secrets.token_urlsafe(24)
        dashboard.shared_at = datetime.now(UTC)
        db.commit()
        db.refresh(dashboard)
    return _dashboard_read(dashboard, 0)


def get_shared_dashboard(db: Session, *, token: str, storage_backend) -> PublicDashboardView:
    """Render a dashboard for someone holding only its share link.

    The token IS the authorisation: it maps to exactly one dashboard and, through
    it, to exactly one project's data -- so there is no `current_user` and no
    `ensure_owned_project`. Revocation is immediate because unshare nulls the
    token, and a null/unknown token simply finds no row. The payload carries
    results only -- no ids, project, dataset or query -- so the link leaks a view,
    not the workspace behind it.
    """
    if not token:
        raise NotFoundError("This shared dashboard is not available.")
    dashboard = db.scalar(select(Dashboard).where(Dashboard.share_token == token))
    if dashboard is None:
        raise NotFoundError("This shared dashboard is not available.")

    tiles, charts = _dashboard_tiles(db, dashboard)
    dashboard_filters = [FilterInput.model_validate(item) for item in (dashboard.filters_json or [])]

    public_tiles: list[PublicChartTile] = []
    for tile in tiles:
        if tile.kind == "text":
            public_tiles.append(
                PublicChartTile(
                    kind="text", name=tile.title or "", description=None, chart_type=None,
                    position=tile.position, width=tile.width, height=tile.height,
                    data=None, body=tile.body,
                )
            )
            continue
        chart = charts.get(tile.chart_id)
        if chart is None:
            continue
        data = _shared_tile_data(db, dashboard.project_id, chart, dashboard_filters, storage_backend)
        public_tiles.append(
            PublicChartTile(
                kind="chart",
                name=chart.name,
                description=chart.description,
                chart_type=chart.chart_type,
                position=tile.position,
                width=tile.width,
                height=tile.height,
                data=data,
            )
        )

    return PublicDashboardView(
        name=dashboard.name,
        description=dashboard.description,
        shared_at=dashboard.shared_at,
        tiles=public_tiles,
    )


def _shared_tile_data(
    db: Session,
    project_id: uuid.UUID,
    chart,
    dashboard_filters: list[FilterInput],
    storage_backend,
) -> ChartDataResponse:
    """Compute one tile's data for the public view. A single broken chart (a
    dataset whose file went missing) must not blank the whole shared page, so it
    degrades to an empty result with a warning."""
    try:
        stored = _from_query(chart.query_json)
        if dashboard_filters:
            stored = stored.model_copy(update={"filters": [*stored.filters, *dashboard_filters]})
        frame = _load_frame(db, project_id, chart.dataset_id, storage_backend)
        data = _compute_chart(chart.chart_type, _to_query(stored), frame, chart.options_json)
        return ChartDataResponse(**data.to_dict())
    except Exception:  # noqa: BLE001 - one bad tile must not fail the page
        from shared_python.logging import get_logger

        get_logger(__name__).exception("shared_tile_data_failed chart_id=%s", chart.id)
        return ChartDataResponse(
            chart_type=chart.chart_type,
            labels=[],
            series=[],
            row_count=0,
            truncated=False,
            warnings=["This chart could not be loaded."],
        )


def unshare_dashboard(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, current_user: UserRead
) -> DashboardRead:
    ensure_owned_project(db, project_id, current_user.id)
    dashboard = _get_dashboard(db, project_id, dashboard_id)
    dashboard.share_token = None
    dashboard.shared_at = None
    db.commit()
    db.refresh(dashboard)
    return _dashboard_read(dashboard, 0)


def delete_dashboard(
    db: Session, project_id: uuid.UUID, dashboard_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    db.delete(_get_dashboard(db, project_id, dashboard_id))
    db.commit()


# --------------------------------------------------------------------------
# Scheduled reports
# --------------------------------------------------------------------------


def _report_read(report: ScheduledReport) -> ReportRead:
    return ReportRead(
        id=report.id,
        project_id=report.project_id,
        name=report.name,
        description=report.description,
        source_kind=report.source_kind,  # type: ignore[arg-type]
        source_id=report.source_id,
        file_format=report.file_format,  # type: ignore[arg-type]
        cron_expression=report.cron_expression,
        timezone=report.timezone,
        enabled=report.enabled,
        next_run_at=report.next_run_at,
        recipients=list(report.recipients_json or []),
        last_run_at=report.last_run_at,
        last_status=report.last_status,
        last_error=report.last_error,
        run_count=report.run_count,
        created_at=report.created_at,
    )


def _apply_report_schedule(report: ScheduledReport) -> None:
    """Work out when this report runs next.

    Reuses the schedule helpers the rest of the platform uses, so a report and a
    workflow interpret the same cron expression identically -- two readings of
    "0 6 * * 1" is exactly the kind of difference nobody finds until Monday.
    """
    from service_schedules.due import compute_first_next_run_utc, resolve_schedule_timezone

    if not report.enabled or not (report.cron_expression or "").strip():
        report.next_run_at = None
        return

    zone = resolve_schedule_timezone(report.timezone)
    report.next_run_at = compute_first_next_run_utc(report.cron_expression, zone)


def create_report(
    db: Session, project_id: uuid.UUID, payload: ReportCreate, current_user: UserRead
) -> ReportRead:
    ensure_owned_project(db, project_id, current_user.id)
    _check_report_source(db, project_id, payload.source_kind, payload.source_id)

    report = ScheduledReport(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description,
        source_kind=payload.source_kind,
        source_id=payload.source_id,
        file_format=payload.file_format,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        enabled=payload.enabled,
        recipients_json=list(payload.recipients) or None,
        created_by_user_id=current_user.id,
    )
    _apply_report_schedule(report)
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_read(report)


def _check_report_source(
    db: Session, project_id: uuid.UUID, source_kind: str, source_id: uuid.UUID
) -> None:
    if source_kind == "dataset":
        _get_dataset(db, project_id, source_id)
    elif source_kind == "chart":
        _get_chart(db, project_id, source_id)
    elif source_kind == "dashboard":
        _get_dashboard(db, project_id, source_id)
    else:
        raise BadRequestError(f"Unknown report source '{source_kind}'.")


def _get_report(db: Session, project_id: uuid.UUID, report_id: uuid.UUID) -> ScheduledReport:
    report = db.scalar(
        select(ScheduledReport).where(
            ScheduledReport.id == report_id, ScheduledReport.project_id == project_id
        )
    )
    if report is None:
        raise NotFoundError("Report not found.")
    return report


def update_report(
    db: Session,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    payload: ReportUpdate,
    current_user: UserRead,
) -> ReportRead:
    ensure_owned_project(db, project_id, current_user.id)
    report = _get_report(db, project_id, report_id)

    if payload.name is not None:
        report.name = payload.name.strip()
    if payload.description is not None:
        report.description = payload.description
    if payload.file_format is not None:
        report.file_format = payload.file_format
    if payload.cron_expression is not None:
        report.cron_expression = payload.cron_expression
    if payload.timezone is not None:
        report.timezone = payload.timezone
    if payload.recipients is not None:
        report.recipients_json = list(payload.recipients) or None
    if payload.enabled is not None:
        report.enabled = payload.enabled

    _apply_report_schedule(report)
    db.commit()
    db.refresh(report)
    return _report_read(report)


def list_reports(db: Session, project_id: uuid.UUID, current_user: UserRead) -> ReportListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    reports = db.scalars(
        select(ScheduledReport)
        .where(ScheduledReport.project_id == project_id)
        .order_by(ScheduledReport.created_at.desc())
    ).all()
    return ReportListResponse(items=[_report_read(report) for report in reports])


def delete_report(
    db: Session, project_id: uuid.UUID, report_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    db.delete(_get_report(db, project_id, report_id))
    db.commit()


def build_report_frame(
    db: Session,
    project_id: uuid.UUID,
    report: ScheduledReport,
    current_user: UserRead,
    storage_backend,
) -> tuple[pd.DataFrame, str]:
    """The numbers that go in the file, and what to call it."""
    if report.source_kind == "dataset":
        dataset = _get_dataset(db, project_id, report.source_id)
        return _load_frame(db, project_id, report.source_id, storage_backend), dataset.name

    if report.source_kind == "chart":
        chart = _get_chart(db, project_id, report.source_id)
        query = _to_query(_from_query(chart.query_json))
        frame = _load_frame(db, project_id, chart.dataset_id, storage_backend)
        return run_query(frame, query).frame, chart.name

    dashboard = _get_dashboard(db, project_id, report.source_id)
    tiles = list(
        db.scalars(
            select(DashboardTile)
            .where(DashboardTile.dashboard_id == dashboard.id)
            .order_by(DashboardTile.position)
        ).all()
    )
    if not tiles:
        raise BadRequestError(f"'{dashboard.name}' has no charts on it yet.")

    # A dashboard is several questions, so its export stacks them with a column
    # saying which is which rather than pretending they are one table.
    frames: list[pd.DataFrame] = []
    for tile in tiles:
        chart = db.get(SavedChart, tile.chart_id)
        if chart is None:
            continue
        query = _to_query(_from_query(chart.query_json))
        source = _load_frame(db, project_id, chart.dataset_id, storage_backend)
        piece = run_query(source, query).frame.copy()
        piece.insert(0, "_chart", chart.name)
        frames.append(piece)

    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    return combined, dashboard.name


def run_report(
    db: Session,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    current_user: UserRead,
    storage_backend,
    *,
    deliver: bool = True,
) -> tuple[bytes, str, str, DeliveryRead]:
    """Generate a report now, and record that it was generated."""
    ensure_owned_project(db, project_id, current_user.id)
    report = _get_report(db, project_id, report_id)

    started = time.perf_counter()
    delivery = ReportDelivery(
        report_id=report.id,
        project_id=project_id,
        status="succeeded",
        file_format=report.file_format,
    )

    try:
        frame, title = build_report_frame(db, project_id, report, current_user, storage_backend)
        result = export(
            frame,
            title=report.name or title,
            file_format=report.file_format,
            subtitle=report.description or f"From {title}.",
        )
    except Exception as exc:  # noqa: BLE001 - the failure belongs on the report
        report.last_status = "failed"
        report.last_error = str(getattr(exc, "detail", exc))[:2000]
        report.last_run_at = datetime.now(UTC)
        delivery.status = "failed"
        delivery.message = report.last_error
        db.add(delivery)
        db.commit()
        raise

    delivery.row_count = result.row_count
    delivery.file_size_bytes = len(result.content)
    delivery.generated_ms = round((time.perf_counter() - started) * 1000, 2)
    delivery.message = f"{result.row_count} row(s)."

    report.last_status = "succeeded"
    report.last_error = None
    report.last_run_at = datetime.now(UTC)
    report.run_count += 1
    _apply_report_schedule(report)

    db.add(delivery)
    if deliver:
        _notify_recipients(db, report, result.filename, result.row_count)
    db.commit()
    db.refresh(delivery)

    return (
        result.content,
        result.filename,
        result.media_type,
        DeliveryRead.model_validate(delivery, from_attributes=True),
    )


def _notify_recipients(
    db: Session, report: ScheduledReport, filename: str, row_count: int
) -> None:
    """Tell people their report is ready.

    Delivery reuses the notification system rather than growing a second one:
    an email path here and an email path in notifications would drift, and only
    one of them would get the retry logic.
    """
    try:
        from service_notifications.service import create_user_notification

        if report.created_by_user_id is None:
            return
        create_user_notification(
            db,
            user_id=report.created_by_user_id,
            project_id=report.project_id,
            type="report",
            level="info",
            title=f"{report.name} is ready",
            message=f"{filename} — {row_count:,} row(s).",
        )
    except Exception:  # noqa: BLE001 - a report that generated is still a success
        from shared_python.logging import get_logger

        get_logger(__name__).exception("report_notify_failed report_id=%s", report.id)


def list_deliveries(
    db: Session, project_id: uuid.UUID, report_id: uuid.UUID, current_user: UserRead
) -> DeliveryListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    _get_report(db, project_id, report_id)
    rows = db.scalars(
        select(ReportDelivery)
        .where(ReportDelivery.report_id == report_id)
        .order_by(ReportDelivery.created_at.desc())
        .limit(50)
    ).all()
    return DeliveryListResponse(
        items=[DeliveryRead.model_validate(row, from_attributes=True) for row in rows]
    )


def due_reports(db: Session, *, now: datetime | None = None) -> list[ScheduledReport]:
    """Reports whose scheduled moment has passed."""
    moment = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(ScheduledReport).where(
                ScheduledReport.enabled.is_(True),
                ScheduledReport.next_run_at.is_not(None),
                ScheduledReport.next_run_at <= moment,
            )
        ).all()
    )


# --------------------------------------------------------------------------
# Catalog and glossary
# --------------------------------------------------------------------------


def _dataset_columns(dataset: Dataset) -> list[str]:
    for candidate in (dataset.schema_json, dataset.schema_snapshot):
        if not isinstance(candidate, dict):
            continue
        ordered = candidate.get("ordered_columns")
        if isinstance(ordered, list) and ordered:
            return [str(name) for name in ordered]
        columns = candidate.get("columns")
        if isinstance(columns, list) and columns:
            names = [
                str(entry.get("name"))
                for entry in columns
                if isinstance(entry, dict) and entry.get("name")
            ]
            if names:
                return names
    return []


def search_catalog(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    query: str = "",
    certified_only: bool = False,
    tag: str | None = None,
    limit: int = 50,
) -> CatalogSearchResponse:
    ensure_owned_project(db, project_id, current_user.id)

    datasets = list(db.scalars(select(Dataset).where(Dataset.project_id == project_id)).all())
    annotations = {
        row.dataset_id: row
        for row in db.scalars(
            select(CatalogAnnotation).where(CatalogAnnotation.project_id == project_id)
        ).all()
    }
    owner_names = _usernames(
        db, [row.owner_user_id for row in annotations.values() if row.owner_user_id]
    )

    searchable = []
    every_tag: set[str] = set()
    for dataset in datasets:
        note = annotations.get(dataset.id)
        tags = list(note.tags_json or []) if note else []
        every_tag.update(tags)
        searchable.append(
            SearchableDataset(
                id=str(dataset.id),
                name=dataset.name,
                description=note.description if note else None,
                columns=_dataset_columns(dataset),
                tags=tags,
                certified=bool(note.certified) if note else False,
                owner=owner_names.get(note.owner_user_id) if note and note.owner_user_id else None,
                row_count=dataset.row_count,
                is_derived=bool(dataset.is_derived),
                column_notes=dict(note.column_notes_json or {}) if note else {},
            )
        )

    hits = search(searchable, query, limit=limit, certified_only=certified_only, tag=tag)
    return CatalogSearchResponse(
        query=query,
        items=[hit.to_dict() for hit in hits],
        total_datasets=len(datasets),
        certified_count=sum(1 for item in searchable if item.certified),
        tags=sorted(every_tag),
    )


def _usernames(db: Session, user_ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    unique = [item for item in dict.fromkeys(user_ids) if item is not None]
    if not unique:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(unique))).all()
    return {row[0]: row[1] for row in rows}


def get_annotation(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> AnnotationRead:
    ensure_owned_project(db, project_id, current_user.id)
    _get_dataset(db, project_id, dataset_id)
    note = db.scalar(
        select(CatalogAnnotation).where(CatalogAnnotation.dataset_id == dataset_id)
    )
    return _annotation_read(db, dataset_id, note)


def _annotation_read(
    db: Session, dataset_id: uuid.UUID, note: CatalogAnnotation | None
) -> AnnotationRead:
    if note is None:
        return AnnotationRead(
            dataset_id=dataset_id,
            description=None,
            tags=[],
            certified=False,
            certified_at=None,
            certified_by_username=None,
            owner_username=None,
            column_notes={},
        )
    names = _usernames(db, [note.owner_user_id, note.certified_by_user_id])
    return AnnotationRead(
        dataset_id=note.dataset_id,
        description=note.description,
        tags=list(note.tags_json or []),
        certified=note.certified,
        certified_at=note.certified_at,
        certified_by_username=names.get(note.certified_by_user_id) if note.certified_by_user_id else None,
        owner_username=names.get(note.owner_user_id) if note.owner_user_id else None,
        column_notes=dict(note.column_notes_json or {}),
    )


def update_annotation(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: AnnotationUpdate,
    current_user: UserRead,
) -> AnnotationRead:
    """Add what the data itself does not say."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    note = db.scalar(select(CatalogAnnotation).where(CatalogAnnotation.dataset_id == dataset_id))
    if note is None:
        note = CatalogAnnotation(
            project_id=project_id, dataset_id=dataset.id, owner_user_id=current_user.id
        )
        db.add(note)
        db.flush()

    if payload.description is not None:
        note.description = payload.description
    if payload.tags is not None:
        cleaned = [tag.strip().lower() for tag in payload.tags if tag.strip()]
        note.tags_json = list(dict.fromkeys(cleaned)) or None
    if payload.column_notes is not None:
        note.column_notes_json = {
            str(key): str(value) for key, value in payload.column_notes.items() if str(value).strip()
        } or None
    if payload.certified is not None and payload.certified != note.certified:
        note.certified = payload.certified
        # Certification is a person putting their name against a dataset, so
        # who and when are part of the claim, not metadata about it.
        note.certified_at = datetime.now(UTC) if payload.certified else None
        note.certified_by_user_id = current_user.id if payload.certified else None

    if payload.owner_username is not None:
        note.owner_user_id = _resolve_owner(db, payload.owner_username)

    db.commit()
    db.refresh(note)
    return _annotation_read(db, dataset_id, note)


def _resolve_owner(db: Session, username: str):
    """Map a username to a user id for the steward field. An empty string clears
    the owner; an unknown username is refused rather than silently ignored."""
    from service_auth.models import User

    cleaned = username.strip().lower()
    if not cleaned:
        return None
    owner = db.scalar(select(User).where(User.username == cleaned))
    if owner is None:
        raise NotFoundError(f"No user named '{cleaned}' to own this dataset.")
    return owner.id


def _term_read(term: GlossaryTerm, owner: str | None) -> TermRead:
    return TermRead(
        id=term.id,
        project_id=term.project_id,
        term=term.term,
        slug=term.slug,
        definition=term.definition,
        synonyms=list(term.synonyms_json or []),
        bindings=[GlossaryBinding.model_validate(item) for item in (term.bindings_json or [])],
        owner_username=owner,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


def create_term(
    db: Session, project_id: uuid.UUID, payload: TermCreate, current_user: UserRead
) -> TermRead:
    ensure_owned_project(db, project_id, current_user.id)
    slug = slugify(payload.term)

    if db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.project_id == project_id, GlossaryTerm.slug == slug
        )
    ):
        raise BadRequestError(
            f"'{payload.term}' is already defined here. Edit that definition instead — "
            "two definitions of one word is the problem a glossary exists to solve."
        )

    for binding in payload.bindings:
        _get_dataset(db, project_id, binding.dataset_id)

    term = GlossaryTerm(
        project_id=project_id,
        term=payload.term.strip(),
        slug=slug,
        definition=payload.definition.strip(),
        owner_user_id=current_user.id,
        synonyms_json=[item.strip() for item in payload.synonyms if item.strip()] or None,
        bindings_json=[item.model_dump(mode="json") for item in payload.bindings] or None,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return _term_read(term, current_user.username)


def update_term(
    db: Session,
    project_id: uuid.UUID,
    term_id: uuid.UUID,
    payload: TermUpdate,
    current_user: UserRead,
) -> TermRead:
    ensure_owned_project(db, project_id, current_user.id)
    term = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.project_id == project_id
        )
    )
    if term is None:
        raise NotFoundError("Term not found.")

    if payload.definition is not None:
        term.definition = payload.definition.strip()
    if payload.synonyms is not None:
        term.synonyms_json = [item.strip() for item in payload.synonyms if item.strip()] or None
    if payload.bindings is not None:
        for binding in payload.bindings:
            _get_dataset(db, project_id, binding.dataset_id)
        term.bindings_json = [item.model_dump(mode="json") for item in payload.bindings] or None

    db.commit()
    db.refresh(term)
    names = _usernames(db, [term.owner_user_id])
    return _term_read(term, names.get(term.owner_user_id) if term.owner_user_id else None)


def list_terms(db: Session, project_id: uuid.UUID, current_user: UserRead) -> TermListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    terms = list(
        db.scalars(
            select(GlossaryTerm)
            .where(GlossaryTerm.project_id == project_id)
            .order_by(GlossaryTerm.term)
        ).all()
    )
    names = _usernames(db, [term.owner_user_id for term in terms])
    return TermListResponse(
        items=[
            _term_read(term, names.get(term.owner_user_id) if term.owner_user_id else None)
            for term in terms
        ]
    )


def list_dataset_terms(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> TermListResponse:
    """Glossary terms linked to this dataset, so a dataset page can show its
    business vocabulary alongside its columns."""
    ensure_owned_project(db, project_id, current_user.id)
    target = str(dataset_id)
    terms = [
        term
        for term in db.scalars(
            select(GlossaryTerm).where(GlossaryTerm.project_id == project_id)
        ).all()
        if any(str(b.get("dataset_id")) == target for b in (term.bindings_json or []))
    ]
    names = _usernames(db, [term.owner_user_id for term in terms])
    return TermListResponse(
        items=[
            _term_read(term, names.get(term.owner_user_id) if term.owner_user_id else None)
            for term in terms
        ]
    )


def link_term_to_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    term_id: uuid.UUID,
    column: str,
    current_user: UserRead,
) -> TermRead:
    """Bind a glossary term to a dataset column, from the dataset's side."""
    ensure_owned_project(db, project_id, current_user.id)
    _get_dataset(db, project_id, dataset_id)  # 404 if not in this project
    term = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.project_id == project_id
        )
    )
    if term is None:
        raise NotFoundError("That glossary term does not exist.")

    target, col = str(dataset_id), column.strip()
    if not col:
        raise BadRequestError("A term is linked to a specific column.")
    bindings = list(term.bindings_json or [])
    if not any(str(b.get("dataset_id")) == target and b.get("column") == col for b in bindings):
        bindings.append({"dataset_id": target, "column": col})
        term.bindings_json = bindings
        db.commit()
        db.refresh(term)
    owner = _usernames(db, [term.owner_user_id]).get(term.owner_user_id) if term.owner_user_id else None
    return _term_read(term, owner)


def unlink_term_from_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    term_id: uuid.UUID,
    column: str,
    current_user: UserRead,
) -> TermRead:
    ensure_owned_project(db, project_id, current_user.id)
    term = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.project_id == project_id
        )
    )
    if term is None:
        raise NotFoundError("That glossary term does not exist.")
    target, col = str(dataset_id), column.strip()
    remaining = [
        b
        for b in (term.bindings_json or [])
        if not (str(b.get("dataset_id")) == target and b.get("column") == col)
    ]
    term.bindings_json = remaining or None
    db.commit()
    db.refresh(term)
    owner = _usernames(db, [term.owner_user_id]).get(term.owner_user_id) if term.owner_user_id else None
    return _term_read(term, owner)


def delete_term(
    db: Session, project_id: uuid.UUID, term_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    term = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.project_id == project_id
        )
    )
    if term is None:
        raise NotFoundError("Term not found.")
    db.delete(term)
    db.commit()


def run_due_reports(db: Session, storage_backend, *, now: datetime | None = None) -> int:
    """Generate every report whose moment has come.

    Called from the worker tick, like the freshness sweep. A scheduled report
    that only runs when somebody opens the page is not scheduled, and the whole
    point is that nobody has to remember.

    One failing report must not stop the rest, so each is caught individually
    and recorded against itself.
    """
    from shared_python.logging import get_logger

    logger = get_logger(__name__)
    generated = 0

    for report in due_reports(db, now=now):
        actor = _report_actor(db, report)
        if actor is None:
            # Nobody left to run it as; disabling it is better than failing
            # silently every minute forever.
            report.enabled = False
            report.last_status = "failed"
            report.last_error = "The person who created this report no longer has an account."
            db.commit()
            continue
        try:
            run_report(db, report.project_id, report.id, actor, storage_backend)
            generated += 1
        except Exception:  # noqa: BLE001 - see docstring
            logger.exception("scheduled_report_failed report_id=%s", report.id)
            db.rollback()
            # `run_report` already recorded the failure and advanced the
            # schedule; re-read it so the loop does not see stale state.
            db.expire_all()

    return generated


def _report_actor(db: Session, report: ScheduledReport) -> UserRead | None:
    if report.created_by_user_id is None:
        return None
    user = db.get(User, report.created_by_user_id)
    if user is None or not user.is_active:
        return None
    return UserRead.model_validate(user)


def total_charts(db: Session) -> int:
    return db.scalar(select(func.count(SavedChart.id))) or 0


def total_dashboards(db: Session) -> int:
    return db.scalar(select(func.count(Dashboard.id))) or 0


def total_reports(db: Session) -> int:
    return db.scalar(select(func.count(ScheduledReport.id))) or 0
