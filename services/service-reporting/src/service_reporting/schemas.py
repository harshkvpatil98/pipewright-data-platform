"""Contracts for charts, dashboards, reports, the catalog, and the glossary."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ChartTypeName = Literal["bar", "column", "line", "area", "scatter", "pie", "kpi", "table"]
AggregationName = Literal[
    "sum", "avg", "mean", "min", "max", "count", "count_distinct", "median"
]
ExportFormat = Literal["excel", "csv", "html"]
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


class ChartDataResponse(BaseModel):
    chart_type: str
    labels: list[Any]
    series: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]


class ChartCreate(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    chart_type: ChartTypeName = "bar"
    query: QueryInput
    options: dict[str, Any] | None = None


class ChartUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    chart_type: ChartTypeName | None = None
    query: QueryInput | None = None
    options: dict[str, Any] | None = None


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


class TileInput(BaseModel):
    chart_id: uuid.UUID
    # None means "wherever it lands in the list". Zero is a real position --
    # the first one -- so the two cannot share a representation.
    position: int | None = Field(default=None, ge=0)
    width: int = Field(default=6, ge=2, le=12)
    height: int = Field(default=1, ge=1, le=4)


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[TileInput] = Field(default_factory=list, max_length=30)
    filters: list[FilterInput] = Field(default_factory=list, max_length=10)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[TileInput] | None = None
    filters: list[FilterInput] | None = None


class TileRead(BaseModel):
    id: uuid.UUID
    chart_id: uuid.UUID
    position: int
    width: int
    height: int
    chart: ChartRead


class DashboardRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    tile_count: int
    share_token: str | None
    shared_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DashboardDetail(DashboardRead):
    tiles: list[TileRead]
    filters: list[FilterInput]


class DashboardListResponse(BaseModel):
    items: list[DashboardRead]


class PublicChartTile(BaseModel):
    """One tile as a public viewer sees it: the chart's name, its shape, and its
    computed data -- and nothing that identifies the project, dataset, or query
    behind it."""

    name: str
    description: str | None
    chart_type: str
    position: int
    width: int
    height: int
    data: ChartDataResponse


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
    enabled: bool = True


class ReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    file_format: ExportFormat | None = None
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    recipients: list[str] | None = None
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
