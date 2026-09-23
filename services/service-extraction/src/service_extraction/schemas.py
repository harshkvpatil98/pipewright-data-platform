from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from service_extraction.connectors.base import LOAD_MODES, SUPPORTED_CONNECTOR_TYPES

_CONNECTOR_PATTERN = "^(" + "|".join(SUPPORTED_CONNECTOR_TYPES) + ")$"
_LOAD_MODE_PATTERN = "^(" + "|".join(LOAD_MODES) + ")$"


class ExtractionConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    connector_type: str = Field(pattern=_CONNECTOR_PATTERN)
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


class DiscoveredTablesResponse(BaseModel):
    items: list[DiscoveredTable]


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

    source_kind: str = Field(default="table", pattern="^(table|query)$")
    schema_name: str | None = Field(default=None, max_length=160)
    table: str | None = Field(default=None, max_length=320)
    query_sql: str | None = None
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
    source_kind: str = Field(default="table", pattern="^(table|query)$")
    schema_name: str | None = Field(default=None, max_length=160)
    table: str | None = Field(default=None, max_length=320)
    query_sql: str | None = None
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


# ------------------------------------------------------------ stream sources

StreamKind = Literal["webhook", "postgres_cdc"]


class StreamSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: StreamKind
    #: postgres_cdc: the PostgreSQL connection whose change log to follow.
    connection_id: uuid.UUID | None = None
    #: postgres_cdc: tables to follow, `schema.table` or `table`.
    tables: list[str] = Field(default_factory=list, max_length=50)
    slot_name: str | None = Field(default=None, max_length=60)


class StreamSourceRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: StreamKind
    status: str
    connection_id: uuid.UUID | None
    connection_name: str | None = None
    tables: list[str] = Field(default_factory=list)
    slot_name: str | None = None
    #: The endpoint's path with the token elided; the token is shown once, at creation.
    webhook_path: str | None = None
    cursor: str | None
    dataset_id: uuid.UUID | None
    dataset_name: str | None = None
    events_count: int
    last_event_at: datetime | None
    last_polled_at: datetime | None
    last_materialised_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class StreamSourceCreated(StreamSourceRead):
    """The read plus the one-time secret: a webhook's token and full path."""

    token: str | None = None
    webhook_path_with_token: str | None = None


class StreamSourceListResponse(BaseModel):
    items: list[StreamSourceRead]


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
    slot_created: bool
    changes_read: int
    events_stored: int
    lines_consumed: int
    upto_lsn: str | None
    note: str


class StreamMaterialiseResponse(BaseModel):
    source: StreamSourceRead
    dataset_id: uuid.UUID
    version_number: int
    rows: int
    columns: list[str]
