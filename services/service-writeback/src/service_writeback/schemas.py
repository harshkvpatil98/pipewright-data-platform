"""API contracts for write-back."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EditKindName = Literal[
    "set_cell", "insert_row", "delete_row", "add_column", "drop_column", "rename_column"
]


class EditInput(BaseModel):
    kind: EditKindName
    key: dict[str, Any] = Field(default_factory=dict)
    column: str | None = None
    value: Any = None
    #: `previous` is only honoured when `has_previous` is set. An explicit null
    #: with the flag means "it was null" -- a claim that gets checked -- while
    #: leaving the flag off means nobody looked, and no check is made.
    previous: Any = None
    has_previous: bool = False
    values: dict[str, Any] = Field(default_factory=dict)
    column_type: str | None = None
    new_name: str | None = None


class EditsCreate(BaseModel):
    edits: list[EditInput] = Field(min_length=1, max_length=5000)


class EditRead(BaseModel):
    id: uuid.UUID
    sequence: int
    kind: str
    payload: dict[str, Any]
    description: str = ""


class ChangeSetCreate(BaseModel):
    connection_id: uuid.UUID
    table_name: str = Field(min_length=1, max_length=200)
    table_schema: str | None = Field(default=None, max_length=200)
    name: str = Field(default="Untitled change", max_length=200)
    #: Columns the caller asserts identify a row, used only when the table has
    #: no key of its own. Verified against live data before it is accepted.
    designated_key: list[str] | None = None


class RowIdentityRead(BaseModel):
    kind: str
    columns: list[str]
    reason: str
    caveat: str = ""
    usable: bool
    durable: bool


class TableShapeRead(BaseModel):
    table: str
    table_schema: str | None
    columns: list[str]
    nullable: list[str]
    types: dict[str, str]
    identity: RowIdentityRead
    editable: bool


class RowPageRead(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    offset: int
    key_columns: list[str]


class ChangeSetRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    connection_id: uuid.UUID
    table_name: str
    table_schema: str | None
    name: str
    status: str
    designated_key: list[str] = []
    rows_affected: int | None
    failure_reason: str | None
    committed_at: datetime | None
    created_at: datetime
    edits: list[EditRead] = []


class ChangeSetListResponse(BaseModel):
    items: list[ChangeSetRead]


class StatementRead(BaseModel):
    sql: str
    describes: str
    kind: str
    expected_rows: int | None
    #: What the rehearsal actually produced. Differs from `expected_rows` when
    #: the data has moved underneath the change.
    actual_rows: int | None = None
    irreversible: bool


class PlanRead(BaseModel):
    """What would run, and what it would touch. Nothing is written to produce this."""

    identity: RowIdentityRead
    statements: list[StatementRead]
    rows_affected: int
    table_rows: int
    blast_radius: str
    needs_confirmation: bool
    has_irreversible: bool
    conflicts: list[str] = []
    warnings: list[str] = []
    ddl_is_not_transactional: bool = False


class CommitRequest(BaseModel):
    #: Required when the change is large: the caller types the table name back.
    confirm_table_name: str | None = None
    #: Proceed even though a statement affects an unexpected number of rows.
    allow_conflicts: bool = False


class CommitRead(BaseModel):
    change_set_id: uuid.UUID
    committed: bool
    rows_affected: int
    statements_run: int
    warnings: list[str] = []


class MigrationRead(BaseModel):
    filename: str
    sql: str
