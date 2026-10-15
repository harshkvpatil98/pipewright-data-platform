from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from service_extraction.connectors.base import LOAD_MODES

_LOAD_MODE_PATTERN = "^(" + "|".join(LOAD_MODES) + ")$"


class ExtractionConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    #: A SQL database (postgresql, mysql, sqlite) or any connector in the
    #: catalogue that can read; checked against the catalogue on create.
    connector_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    description: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] = Field(default_factory=dict)


class ExtractionConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    config: dict[str, Any] | None = None


class ExtractionConnectionRead(BaseModel):
    """Connection as returned by the API. Secret fields are never included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    connector_type: str
    description: str | None
    status: str
    config_json: dict[str, Any]
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str | None
    created_at: datetime
    updated_at: datetime


class ExtractionConnectionListResponse(BaseModel):
    items: list[ExtractionConnectionRead]


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
    server_version: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DiscoveredTable(BaseModel):
    schema_name: str | None
    name: str
    kind: str
    qualified_name: str
    #: What a connector needs to read this back beyond its name (a path, a URL).
    detail: dict[str, Any] = Field(default_factory=dict)


class DiscoveredTablesResponse(BaseModel):
    items: list[DiscoveredTable]
    #: False for a connector that cannot list what it holds (a single API
    #: endpoint): it is imported whole.
    can_list: bool = True
    #: True when imports can bring only what is new since the last run.
    can_resume: bool = False


class DiscoveredColumnRead(BaseModel):
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


class DiscoveredColumnsResponse(BaseModel):
    table: str
    schema_name: str | None
    items: list[DiscoveredColumnRead]


class ExtractionPreviewRequest(BaseModel):
    """Ad hoc preview of a table or query before a job is saved."""

    source_kind: str = Field(default="table", pattern="^(table|query|stream)$")
    schema_name: str | None = Field(default=None, max_length=160)
    table: str | None = Field(default=None, max_length=320)
    query_sql: str | None = None
    #: source_kind "stream": what a connector listed, or None for everything.
    stream: dict[str, Any] | None = None
    limit: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def _require_source(self) -> ExtractionPreviewRequest:
        if self.source_kind == "table" and not (self.table or "").strip():
            raise ValueError("table is required when source_kind is 'table'.")
        if self.source_kind == "query" and not (self.query_sql or "").strip():
            raise ValueError("query_sql is required when source_kind is 'query'.")
        return self


class ExtractionPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str] = Field(default_factory=list)


class ExtractionJobBase(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    source_kind: str = Field(default="table", pattern="^(table|query|stream)$")
    schema_name: str | None = Field(default=None, max_length=160)
    table: str | None = Field(default=None, max_length=320)
    query_sql: str | None = None
    #: source_kind "stream" (any connector but the SQL databases): the stream
    #: to import, as the connector listed it, or None for everything it returns.
    stream: dict[str, Any] | None = None
    load_mode: str = Field(default="full_refresh", pattern=_LOAD_MODE_PATTERN)
    cursor_column: str | None = Field(default=None, max_length=160)
    primary_key_columns: list[str] = Field(default_factory=list)
    max_rows: int = Field(default=1_000_000, ge=1, le=10_000_000)
    #: Transformation steps to apply at extraction. The pushable prefix runs in
    #: the source database; the rest runs here before the dataset is written.
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _validate_combination(self) -> ExtractionJobBase:
        if self.source_kind == "table" and not (self.table or "").strip():
            raise ValueError("table is required when source_kind is 'table'.")
        if self.source_kind == "query" and not (self.query_sql or "").strip():
            raise ValueError("query_sql is required when source_kind is 'query'.")
        if self.source_kind == "stream":
            # A connector keeps its own place ("only new rows" resumes from
            # where the last run stopped), so there is no cursor column.
            if self.load_mode == "incremental_merge":
                raise ValueError("Imports from this kind of source can bring all rows or only new ones.")
            return self
        if self.load_mode != "full_refresh" and not (self.cursor_column or "").strip():
            raise ValueError("cursor_column is required for incremental load modes.")
        if self.load_mode == "incremental_merge" and not self.primary_key_columns:
            raise ValueError("primary_key_columns is required for incremental_merge.")
        return self


class ExtractionJobCreate(ExtractionJobBase):
    connection_id: uuid.UUID


class ExtractionJobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    load_mode: str | None = Field(default=None, pattern=_LOAD_MODE_PATTERN)
    cursor_column: str | None = Field(default=None, max_length=160)
    primary_key_columns: list[str] | None = None
    max_rows: int | None = Field(default=None, ge=1, le=10_000_000)
    steps: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class ExtractionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    connection_id: uuid.UUID
    name: str
    description: str | None
    source_kind: str
    source_schema: str | None
    source_table: str | None
    query_sql: str | None
    stream_json: dict[str, Any] | None = None
    load_mode: str
    cursor_column: str | None
    primary_key_columns: list[str] | None
    max_rows: int
    steps: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("steps", "steps_json"))
    watermark_value: str | None
    watermark_updated_at: datetime | None
    target_dataset_id: uuid.UUID | None
    enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    last_row_count: int | None
    last_error_message: str | None
    execution_count: int
    created_at: datetime
    updated_at: datetime

    @field_validator("steps", mode="before")
    @classmethod
    def _no_steps_is_an_empty_list(cls, value: Any) -> Any:
        # A job without shaping steps stores NULL (create_job writes `or
        # None`). Reading that as "not a list" made every such job a 500 --
        # the job list, and with it the whole Sources page, for any project
        # with a plain import.
        return [] if value is None else value


class ExtractionJobListResponse(BaseModel):
    items: list[ExtractionJobRead]


class ExtractionRunResponse(BaseModel):
    """Result of running one extraction job."""

    job: ExtractionJobRead
    dataset_id: uuid.UUID
    run_id: uuid.UUID
    rows_extracted: int
    rows_added: int
    rows_updated: int
    total_rows: int
    load_mode: str
    watermark_value: str | None
    truncated: bool
    warnings: list[str] = Field(default_factory=list)
    #: Where the job's steps ran, when it has any: pushed vs local, the SQL the
    #: source ran, and the reason for every placement.
    shaping: dict[str, Any] | None = None


# ------------------------------------------------------------ live sources

StreamKind = Literal[
    "webhook", "postgres_cdc", "mysql_cdc", "mongodb_cdc", "sqlserver_cdc", "kafka", "event_hubs", "kinesis",
    "pubsub", "pulsar", "rabbitmq", "nats", "mqtt",
]


class StreamSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: StreamKind
    #: Change capture through a project connection: which one.
    connection_id: uuid.UUID | None = None
    #: Change capture: tables (or collections) to follow, `schema.table` or `table`.
    tables: list[str] = Field(default_factory=list, max_length=50)
    slot_name: str | None = Field(default=None, max_length=60)
    #: The kind's own settings (see `GET /live/kinds`); secrets are stored encrypted.
    settings: dict[str, Any] = Field(default_factory=dict)
    read_every_seconds: int = Field(default=5, ge=1, le=3600)
    save_every_seconds: int = Field(default=60, ge=5, le=86400)


class StreamSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    status: Literal["active", "paused"] | None = None
    tables: list[str] | None = Field(default=None, max_length=50)
    #: A secret left out or blank keeps the saved one.
    settings: dict[str, Any] | None = None
    read_every_seconds: int | None = Field(default=None, ge=1, le=3600)
    save_every_seconds: int | None = Field(default=None, ge=5, le=86400)
    keep_events_hours: int | None = Field(default=None, ge=1, le=24 * 90)


class StreamTestRequest(BaseModel):
    kind: StreamKind
    connection_id: uuid.UUID | None = None
    tables: list[str] = Field(default_factory=list, max_length=50)
    settings: dict[str, Any] = Field(default_factory=dict)
    #: Testing a saved source's edited settings: secrets left blank keep its saved ones.
    source_id: uuid.UUID | None = None


class LiveTestResult(BaseModel):
    ok: bool
    message: str
    details: list[str] = Field(default_factory=list)


class LiveTableRead(BaseModel):
    id: uuid.UUID
    table_name: str
    key_columns: list[str]
    dataset_id: uuid.UUID | None
    #: waiting, snapshot, following, log_only or failed.
    state: str
    snapshot_rows: int | None
    rows_now: int | None
    applied_seq: int
    last_saved_at: datetime | None
    last_error: str | None


class StreamSourceRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: StreamKind
    kind_label: str
    family: Literal["webhook", "change_capture", "queue"]
    guarantee: Literal["position", "message_id", "at_least_once"]
    guarantee_title: str
    guarantee_detail: str
    tier: int
    tier_label: str
    #: active, paused, or failing (still read, backing off).
    status: str
    connection_id: uuid.UUID | None
    connection_name: str | None = None
    tables: list[str] = Field(default_factory=list)
    slot_name: str | None = None
    #: The kind's settings; a secret shows only whether it is set.
    settings: dict[str, Any] = Field(default_factory=dict)
    #: The endpoint's path with the token elided; the token is shown once, at creation.
    webhook_path: str | None = None
    cursor: str | None
    dataset_id: uuid.UUID | None
    dataset_name: str | None = None
    events_count: int
    behind: int | None = None
    read_every_seconds: int
    save_every_seconds: int
    keep_events_hours: int
    failures: int
    next_read_at: datetime | None
    last_read_count: int
    last_event_at: datetime | None
    last_polled_at: datetime | None
    last_materialised_at: datetime | None
    last_error: str | None
    live_tables: list[LiveTableRead] = Field(default_factory=list)
    live_recipe_count: int = 0
    created_at: datetime
    updated_at: datetime


class StreamSourceCreated(StreamSourceRead):
    """The read plus the one-time secret: a webhook's token and full path."""

    token: str | None = None
    webhook_path_with_token: str | None = None


class StreamSourceListResponse(BaseModel):
    items: list[StreamSourceRead]


class LiveKindField(BaseModel):
    key: str
    label: str
    kind: str
    required: bool
    default: Any = None
    help: str = ""
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)


class LiveKindRead(BaseModel):
    key: str
    label: str
    family: Literal["webhook", "change_capture", "queue"]
    description: str
    fields: list[LiveKindField]
    connection_types: list[str]
    guarantee: str
    guarantee_title: str
    guarantee_detail: str
    tier: int
    tier_label: str
    tier_badge: str
    tier_explanation: str
    verified_by: str
    available: bool
    unavailable_reason: str | None = None


class LiveKindListResponse(BaseModel):
    items: list[LiveKindRead]


class StreamEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    seq: int
    kind: str
    table_name: str | None
    position: str | None
    payload_json: dict[str, Any]
    received_at: datetime


class StreamEventListResponse(BaseModel):
    items: list[StreamEventRead]


class StreamPollResponse(BaseModel):
    source: StreamSourceRead
    read: int
    stored: int
    rounds: int
    notes: list[str] = Field(default_factory=list)
    guarantee: str


class StreamMaterialiseResponse(BaseModel):
    source: StreamSourceRead
    dataset_id: uuid.UUID | None
    version_number: int
    events_saved: int
    changes_applied: int
    recipe_outputs: int


class ThroughputPoint(BaseModel):
    minute: datetime
    events: int


class ThroughputResponse(BaseModel):
    items: list[ThroughputPoint]


# ------------------------------------------------------------- live recipes


class LookupPair(BaseModel):
    event: str = Field(min_length=1, max_length=200)
    dataset: str = Field(min_length=1, max_length=200)


class LiveLookup(BaseModel):
    dataset_id: uuid.UUID
    on: list[LookupPair] = Field(min_length=1, max_length=5)
    columns: list[str] = Field(min_length=1, max_length=50)
    #: Keep an event no row matches (its looked-up columns empty), or drop it.
    keep_unmatched: bool = True


class LiveWindow(BaseModel):
    kind: Literal["tumbling", "hopping", "sliding", "session"]
    size_seconds: float | None = Field(default=None, gt=0, le=31 * 86400)
    advance_seconds: float | None = Field(default=None, gt=0, le=31 * 86400)
    gap_seconds: float | None = Field(default=None, gt=0, le=31 * 86400)
    #: The column holding each event's time; `received_at` is when it arrived.
    time_column: str = Field(default="received_at", min_length=1, max_length=200)
    lateness_seconds: float = Field(default=0, ge=0, le=7 * 86400)
    #: drop: a late event is counted and left out. restate: it updates a window
    #: closed within `restate_for_seconds`, which is marked restated.
    late: Literal["drop", "restate"] = "drop"
    restate_for_seconds: float = Field(default=0, ge=0, le=31 * 86400)


class LiveMeasure(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    op: Literal["count", "sum", "average", "lowest", "highest", "first", "last"]
    column: str | None = Field(default=None, max_length=200)


class LiveRecipeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    #: A saved recipe whose steps (row by row) run on each batch.
    recipe_id: uuid.UUID | None = None
    lookup: LiveLookup | None = None
    window: LiveWindow | None = None
    group_by: list[str] = Field(default_factory=list, max_length=10)
    measures: list[LiveMeasure] = Field(default_factory=list, max_length=20)


class LiveRecipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    status: Literal["active", "paused"] | None = None
    recipe_id: uuid.UUID | None = None
    clear_recipe: bool = False
    lookup: LiveLookup | None = None
    clear_lookup: bool = False
    window: LiveWindow | None = None
    group_by: list[str] | None = Field(default=None, max_length=10)
    measures: list[LiveMeasure] | None = Field(default=None, max_length=20)


class LiveRecipeRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    name: str
    recipe_id: uuid.UUID | None
    lookup: dict[str, Any] | None
    window: dict[str, Any] | None
    group_by: list[str]
    measures: list[dict[str, Any]]
    output_dataset_id: uuid.UUID | None
    output_dataset_name: str | None
    #: active, paused, or failed (stopped with `last_error` until edited or resumed).
    status: str
    last_error: str | None
    processed_seq: int
    events_in: int
    late_dropped: int
    late_restated: int
    without_time: int
    unmatched: int
    open_windows: int
    #: The watermark: every window ending by then is final.
    complete_up_to: datetime | None
    description: str
    last_processed_at: datetime | None
    last_saved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LiveRecipeListResponse(BaseModel):
    items: list[LiveRecipeRead]


class LiveRecipeResultRead(BaseModel):
    window_start: datetime
    window_end: datetime
    group: list[Any]
    values: dict[str, Any]
    events: int
    final: bool
    restated: int


class LiveRecipeResultsResponse(BaseModel):
    recipe: LiveRecipeRead
    group_by: list[str]
    measures: list[str]
    items: list[LiveRecipeResultRead]
