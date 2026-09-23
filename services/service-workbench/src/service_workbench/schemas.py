"""API contracts for the workbench."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from service_workbench.sql_text import MAX_SCRIPT_LENGTH


class StatementRead(BaseModel):
    index: int
    sql: str
    summary: str
    kind: str
    line: int
    start: int
    end: int
    parameters: list[str] = []


class VerdictRead(BaseModel):
    allowed: bool
    reason: str = ""
    warnings: list[str] = []
    needs_confirmation: bool = False


class PolicyRead(BaseModel):
    allow_writes: bool
    allow_ddl: bool
    environment: str
    row_limit: int
    description: str


class ScriptPlanRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=MAX_SCRIPT_LENGTH)
    allow_writes: bool = False
    allow_ddl: bool = False


class ScriptPlanResponse(BaseModel):
    statements: list[StatementRead]
    parameters: list[str]
    policy: PolicyRead
    verdict: VerdictRead


class RunRequest(BaseModel):
    connection_id: uuid.UUID
    sql: str = Field(min_length=1, max_length=MAX_SCRIPT_LENGTH)
    parameters: dict[str, Any] = Field(default_factory=dict)
    allow_writes: bool = False
    allow_ddl: bool = False
    saved_query_id: uuid.UUID | None = None


class StatementResultRead(BaseModel):
    index: int
    sql: str
    summary: str
    kind: str
    duration_ms: float
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    rows_affected: int | None = None
    error: str | None = None
    skipped: bool = False


class RunResponse(BaseModel):
    statements: list[StatementResultRead]
    duration_ms: float
    committed: bool
    warnings: list[str] = []
    policy: str


class TemporalQueryRequest(BaseModel):
    """SQL over one recorded version of a stored dataset (time travel).

    Exactly one of `version_number` / `as_of` picks the version; neither means
    the current head. The data is exposed as a table named `dataset`.
    """

    sql: str = Field(min_length=1, max_length=MAX_SCRIPT_LENGTH)
    version_number: int | None = Field(default=None, ge=1)
    as_of: datetime | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    row_limit: int = Field(default=200, ge=1, le=1000)


class TemporalQueryResponse(BaseModel):
    dataset_id: uuid.UUID
    #: The version the request resolved to.
    version_number: int
    version_published_at: datetime
    requested_as_of: datetime | None = None
    table_name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    #: True when more rows matched than `row_limit` allowed back.
    truncated: bool
    row_limit: int
    duration_ms: float
    warnings: list[str] = []


class ExplainRequest(BaseModel):
    connection_id: uuid.UUID
    sql: str = Field(min_length=1, max_length=MAX_SCRIPT_LENGTH)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExplainResponse(BaseModel):
    dialect: str
    text: str
    rows: list[dict[str, Any]] = []
    estimated_cost: float | None = None
    estimated_rows: int | None = None
    notes: list[str] = []


class ColumnRead(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool


class TableRead(BaseModel):
    name: str
    table_schema: str | None
    kind: str
    qualified: str
    columns: list[ColumnRead] = []
    loaded: bool = False


class SchemaResponse(BaseModel):
    dialect: str
    default_schema: str | None
    tables: list[TableRead]
    truncated: bool = False


class CompletionRead(BaseModel):
    label: str
    kind: str
    detail: str = ""
    insert: str = ""


class CompletionRequest(BaseModel):
    """Sent as a body, not a query string.

    A script can be tens of thousands of characters, and a URL that long is
    refused by most proxies well before it reaches the gateway -- so
    autocomplete would work while somebody was writing a short query and stop
    working exactly as their script got big enough to need it.
    """

    sql: str = Field(default="", max_length=MAX_SCRIPT_LENGTH)
    offset: int | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class CompletionResponse(BaseModel):
    items: list[CompletionRead]


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sql: str = Field(min_length=1, max_length=MAX_SCRIPT_LENGTH)
    description: str | None = Field(default=None, max_length=2000)
    connection_id: uuid.UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class SavedQueryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    sql: str | None = Field(default=None, max_length=MAX_SCRIPT_LENGTH)
    description: str | None = Field(default=None, max_length=2000)
    connection_id: uuid.UUID | None = None
    parameters: dict[str, Any] | None = None


class SavedQueryRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    connection_id: uuid.UUID | None
    name: str
    description: str | None
    sql: str
    parameters: dict[str, Any]
    run_count: int
    last_run_at: datetime | None
    created_at: datetime


class SavedQueryListResponse(BaseModel):
    items: list[SavedQueryRead]


class QueryRunRead(BaseModel):
    id: uuid.UUID
    sql: str
    statement_count: int
    wrote: bool
    succeeded: bool
    duration_ms: float
    rows_returned: int
    rows_affected: int
    error: str | None
    created_at: datetime


class QueryRunListResponse(BaseModel):
    items: list[QueryRunRead]


class CellInput(BaseModel):
    kind: Literal["sql", "python", "recipe", "markdown"] = "sql"
    source: str = ""
    output_name: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)


class CellRead(CellInput):
    id: uuid.UUID
    position: int


class NotebookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    connection_id: uuid.UUID | None = None
    cells: list[CellInput] = Field(default_factory=list, max_length=200)


class NotebookUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    connection_id: uuid.UUID | None = None
    cells: list[CellInput] | None = Field(default=None, max_length=200)


class NotebookRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    connection_id: uuid.UUID | None
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    cells: list[CellRead] = []


class NotebookListResponse(BaseModel):
    items: list[NotebookRead]


class NotebookRunRequest(BaseModel):
    allow_writes: bool = False
    #: Run up to and including this cell, for "run everything above".
    only_to: int | None = Field(default=None, ge=0)


class CellResultRead(BaseModel):
    position: int
    kind: str
    ok: bool
    duration_ms: float
    output_name: str | None = None
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    stdout: str = ""
    error: str = ""
    skipped: bool = False
    bindings: dict[str, str] = {}


class NotebookRunResponse(BaseModel):
    cells: list[CellResultRead]
    duration_ms: float


class SandboxCapabilityRead(BaseModel):
    name: str
    available: bool
    detail: str


class SandboxStatusResponse(BaseModel):
    usable: bool
    reason: str
    python: str
    platform: str
    allowed_imports: list[str]
    capabilities: list[SandboxCapabilityRead]
    limits: dict[str, int]


class RecipeYamlRequest(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    dataset: str | None = Field(default=None, max_length=200)


class RecipeYamlResponse(BaseModel):
    yaml: str


class RecipeParseRequest(BaseModel):
    yaml: str = Field(min_length=1, max_length=500_000)


class RecipeParseResponse(BaseModel):
    version: int
    name: str | None = None
    description: str | None = None
    dataset: str | None = None
    steps: list[dict[str, Any]]
