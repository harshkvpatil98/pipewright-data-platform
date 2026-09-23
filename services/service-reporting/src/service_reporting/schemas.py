"""Contracts for charts, dashboards, reports, the catalog, and the glossary."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ChartTypeName = Literal["bar", "column", "line", "area", "scatter", "pie", "donut", "kpi", "table"]
AggregationName = Literal[
    "sum", "avg", "mean", "min", "max", "count", "count_distinct", "median"
]
ExportFormat = Literal["excel", "csv", "html", "pdf"]
ReportSource = Literal["dataset", "chart", "dashboard"]


class MeasureInput(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    aggregation: AggregationName = "sum"
    label: str | None = Field(default=None, max_length=120)


class FilterInput(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    operator: str = "equals"
    value: Any = None


class QueryInput(BaseModel):
    dimensions: list[str] = Field(default_factory=list, max_length=4)
    measures: list[MeasureInput] = Field(default_factory=list, max_length=6)
    filters: list[FilterInput] = Field(default_factory=list, max_length=20)
    sort_by: str | None = None
    descending: bool = True
    limit: int | None = Field(default=None, ge=1, le=500)


class ChartTypeRead(BaseModel):
    name: str
    label: str
    description: str
    min_dimensions: int
    max_dimensions: int
    min_measures: int
    max_measures: int
    max_categories: int | None


class ChartCatalogResponse(BaseModel):
    items: list[ChartTypeRead]
    aggregations: list[str]
    filter_operators: list[str]


class ChartPreviewRequest(BaseModel):
    dataset_id: uuid.UUID
    chart_type: ChartTypeName = "bar"
    query: QueryInput
    #: Chart options the preview should honour -- a KPI's `compare` block.
    options: dict[str, Any] | None = None
    #: Take the measure and filters from this metric; the query then carries
    #: dimensions, extra filters, sort and limit only.
    metric_id: uuid.UUID | None = None


class ChartDataResponse(BaseModel):
    chart_type: str
    labels: list[Any]
    series: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]
    #: Extra facts a renderer can use: for a KPI with a period comparison, the
    #: `delta` block (previous value, change, change_pct, period labels).
    meta: dict[str, Any] | None = None


class ChartCreate(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    chart_type: ChartTypeName = "bar"
    query: QueryInput
    options: dict[str, Any] | None = None
    metric_id: uuid.UUID | None = None


class ChartUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    chart_type: ChartTypeName | None = None
    query: QueryInput | None = None
    options: dict[str, Any] | None = None
    #: Send explicitly as null to detach the chart from its metric.
    metric_id: uuid.UUID | None = None


class ChartRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    name: str
    description: str | None
    chart_type: str
    query: QueryInput
    options: dict[str, Any] | None
    metric_id: uuid.UUID | None = None
    metric_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ChartListResponse(BaseModel):
    items: list[ChartRead]


class ChartWithData(ChartRead):
    data: ChartDataResponse


class PivotRequest(BaseModel):
    dataset_id: uuid.UUID
    rows: list[str] = Field(default_factory=list, max_length=3)
    columns: list[str] = Field(default_factory=list, max_length=2)
    measure: MeasureInput
    filters: list[FilterInput] = Field(default_factory=list, max_length=20)


class PivotResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    warnings: list[str]


TileKind = Literal["chart", "text"]

#: The refresh cadences a dashboard may pick. A free integer would let someone
#: set one second and hammer the gateway from an open tab.
REFRESH_CHOICES = (30, 60, 300, 900, 1800, 3600)


class TileInput(BaseModel):
    kind: TileKind = "chart"
    chart_id: uuid.UUID | None = None
    #: Text tiles: a heading and a body. A chart tile ignores both (the chart
    #: has its own name).
    title: str | None = Field(default=None, max_length=160)
    body: str | None = Field(default=None, max_length=4000)
    # None means "wherever it lands in the list". Zero is a real position --
    # the first one -- so the two cannot share a representation.
    position: int | None = Field(default=None, ge=0)
    width: int = Field(default=6, ge=2, le=12)
    height: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def _kind_matches_fields(self) -> "TileInput":
        if self.kind == "chart" and self.chart_id is None:
            raise ValueError("A chart tile needs a chart_id.")
        if self.kind == "text" and not (self.body or "").strip() and not (self.title or "").strip():
            raise ValueError("A text tile needs a title or a body.")
        return self


def _validate_refresh(value: int | None) -> int | None:
    if value is None or value == 0:
        return None
    if value not in REFRESH_CHOICES:
        raise ValueError(
            "refresh_seconds must be one of " + ", ".join(str(item) for item in REFRESH_CHOICES) + " (or null)."
        )
    return value


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[TileInput] = Field(default_factory=list, max_length=30)
    filters: list[FilterInput] = Field(default_factory=list, max_length=10)
    refresh_seconds: int | None = None

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh(cls, value: int | None) -> int | None:
        return _validate_refresh(value)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[TileInput] | None = None
    filters: list[FilterInput] | None = None
    #: Explicit null in the body (present, None) turns auto-refresh off; leave
    #: the field out to keep the current cadence.
    refresh_seconds: int | None = None

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh(cls, value: int | None) -> int | None:
        return _validate_refresh(value)


class TileRead(BaseModel):
    id: uuid.UUID
    kind: TileKind = "chart"
    chart_id: uuid.UUID | None
    title: str | None = None
    body: str | None = None
    position: int
    width: int
    height: int
    chart: ChartRead | None = None


class DashboardRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    tile_count: int
    share_token: str | None
    shared_at: datetime | None
    refresh_seconds: int | None = None
    created_at: datetime
    updated_at: datetime


class DashboardDataRequest(BaseModel):
    """Compute every tile. `filters`, when given, REPLACE the dashboard's saved
    filters for this computation only (an ad-hoc scope); omit it to use the
    saved ones."""

    filters: list[FilterInput] | None = Field(default=None, max_length=10)


class DashboardTileData(BaseModel):
    tile_id: uuid.UUID
    kind: TileKind
    position: int
    width: int
    height: int
    title: str | None = None
    body: str | None = None
    chart_id: uuid.UUID | None = None
    chart_name: str | None = None
    chart_type: str | None = None
    data: ChartDataResponse | None = None
    #: Why this tile has no data, when it has none. One broken chart never
    #: blanks the page.
    error: str | None = None


class DashboardDataResponse(BaseModel):
    dashboard_id: uuid.UUID
    computed_at: datetime
    filters_applied: list[FilterInput]
    tiles: list[DashboardTileData]


class DashboardDetail(DashboardRead):
    tiles: list[TileRead]
    filters: list[FilterInput]


class DashboardListResponse(BaseModel):
    items: list[DashboardRead]


class PublicChartTile(BaseModel):
    """One tile as a public viewer sees it: the chart's name, its shape, and its
    computed data -- and nothing that identifies the project, dataset, or query
    behind it. A text tile carries its title and body and no data."""

    kind: TileKind = "chart"
    name: str
    description: str | None
    chart_type: str | None = None
    position: int
    width: int
    height: int
    data: ChartDataResponse | None = None
    body: str | None = None


class PublicDashboardView(BaseModel):
    """A shared dashboard rendered for someone with only the link. Deliberately
    minimal: a title, a note, and the tiles -- no ids, no project, no query, so
    the token grants a view of results and nothing else about the workspace."""

    name: str
    description: str | None
    shared_at: datetime | None
    tiles: list[PublicChartTile]


class ReportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    source_kind: ReportSource = "dataset"
    source_id: uuid.UUID
    file_format: ExportFormat = "excel"
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    recipients: list[str] = Field(default_factory=list, max_length=50)
    #: A Slack webhook or email notification target of this project to deliver
    #: to, on top of the recipients.
    notification_target_id: uuid.UUID | None = None
    enabled: bool = True


class ReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    file_format: ExportFormat | None = None
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    recipients: list[str] | None = None
    #: Send explicitly as null to clear; omit to keep.
    notification_target_id: uuid.UUID | None = None
    enabled: bool | None = None


class ReportRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    source_kind: ReportSource
    source_id: uuid.UUID
    file_format: ExportFormat
    cron_expression: str | None
    timezone: str | None
    enabled: bool
    next_run_at: datetime | None
    recipients: list[str]
    notification_target_id: uuid.UUID | None = None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    run_count: int
    created_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportRead]


class DeliveryRead(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    status: str
    file_format: str
    file_size_bytes: int | None
    row_count: int | None
    generated_ms: float | None
    message: str | None
    #: Where it went, per channel: `{"channel": "slack"|"email"|"in_app",
    #: "ok": bool, "detail": str, "target"?: str, "recipient"?: str}`.
    channels: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class DeliveryListResponse(BaseModel):
    items: list[DeliveryRead]


class CatalogSearchResponse(BaseModel):
    query: str
    items: list[dict[str, Any]]
    total_datasets: int
    certified_count: int
    tags: list[str]


class AnnotationUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=20)
    certified: bool | None = None
    column_notes: dict[str, str] | None = None
    # The steward responsible for this dataset, by username. Empty string clears
    # it; None leaves it unchanged.
    owner_username: str | None = Field(default=None, max_length=80)


class AnnotationRead(BaseModel):
    dataset_id: uuid.UUID
    description: str | None
    tags: list[str]
    certified: bool
    certified_at: datetime | None
    certified_by_username: str | None
    owner_username: str | None
    column_notes: dict[str, str]


class GlossaryBinding(BaseModel):
    dataset_id: uuid.UUID
    column: str = Field(min_length=1, max_length=200)


class DatasetTermLink(BaseModel):
    """Link an existing glossary term to one column of this dataset."""

    term_id: uuid.UUID
    column: str = Field(min_length=1, max_length=200)


class TermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=4000)
    synonyms: list[str] = Field(default_factory=list, max_length=20)
    bindings: list[GlossaryBinding] = Field(default_factory=list, max_length=50)


class TermUpdate(BaseModel):
    definition: str | None = Field(default=None, min_length=1, max_length=4000)
    synonyms: list[str] | None = None
    bindings: list[GlossaryBinding] | None = None


class TermRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    term: str
    slug: str
    definition: str
    synonyms: list[str]
    bindings: list[GlossaryBinding]
    owner_username: str | None
    created_at: datetime
    updated_at: datetime


class TermListResponse(BaseModel):
    items: list[TermRead]


# --------------------------------------------------------------- metrics


class MetricCreate(BaseModel):
    """One definition of a number. Either `column` or `formula` (the spreadsheet
    language, evaluated per row before aggregation); never both."""

    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    owner_username: str | None = Field(default=None, max_length=80)
    aggregation: AggregationName = "sum"
    column: str | None = Field(default=None, max_length=200)
    formula: str | None = Field(default=None, max_length=4000)
    filters: list[FilterInput] = Field(default_factory=list, max_length=20)
    #: Dimensions this metric may be cut by. Empty means any column.
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    valid_from: date | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "MetricCreate":
        has_column = bool((self.column or "").strip())
        has_formula = bool((self.formula or "").strip())
        if has_column == has_formula:
            raise ValueError("Give either a column or a formula for the metric, not both and not neither.")
        return self


class MetricUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    #: "" clears the owner.
    owner_username: str | None = Field(default=None, max_length=80)
    aggregation: AggregationName | None = None
    column: str | None = Field(default=None, max_length=200)
    formula: str | None = Field(default=None, max_length=4000)
    filters: list[FilterInput] | None = None
    dimensions: list[str] | None = None
    valid_from: date | None = None


class MetricRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    name: str
    slug: str
    description: str | None
    owner_username: str | None
    aggregation: str
    column: str | None
    formula: str | None
    filters: list[FilterInput]
    dimensions: list[str]
    valid_from: date | None
    version_number: int
    #: Charts that resolve through this metric -- what moves if it changes.
    used_by_charts: int = 0
    created_at: datetime
    updated_at: datetime


class MetricListResponse(BaseModel):
    items: list[MetricRead]


class MetricPreviewRequest(BaseModel):
    dimensions: list[str] = Field(default_factory=list, max_length=4)
    filters: list[FilterInput] = Field(default_factory=list, max_length=20)
    limit: int | None = Field(default=None, ge=1, le=500)


class MetricPreviewResponse(BaseModel):
    metric_id: uuid.UUID
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]


class MetricSqlResponse(BaseModel):
    metric_id: uuid.UUID
    dialect: str
    #: The definition rendered as one SELECT, or null with `reason` when the
    #: dialect cannot express it (a formula function without a lowering).
    sql: str | None
    reason: str | None = None
    #: The table name the SQL reads from; the person substitutes their own.
    source_placeholder: str


class MetricUsageChart(BaseModel):
    chart_id: uuid.UUID
    chart_name: str
    chart_type: str
    dashboards: list[str] = Field(default_factory=list)


class MetricUsageResponse(BaseModel):
    metric_id: uuid.UUID
    charts: list[MetricUsageChart]
