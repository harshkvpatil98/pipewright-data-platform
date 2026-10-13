"""API shapes for copying a database into a destination."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CopyRequest(BaseModel):
    connection_id: uuid.UUID
    destination_id: uuid.UUID
    #: Tables to copy, as the source lists them (schema.table or table). Empty means every table.
    tables: list[str] = Field(default_factory=list, max_length=500)
    #: A table of the same name already in the destination is replaced (True) or left alone (False).
    replace_existing: bool = False


class CopyColumnPlan(BaseModel):
    name: str
    source_type: str
    target_type: str
    nullable: bool
    primary_key: bool
    #: True when the destination's type does not hold every value exactly.
    lossy: bool = False
    note: str | None = None


class CopyTablePlan(BaseModel):
    source: str
    target: str
    columns: list[CopyColumnPlan]
    primary_key: list[str]
    #: What this table has that will not be copied.
    not_carried: list[str] = Field(default_factory=list)
    #: Why this table cannot be copied as it is, when it cannot.
    problem: str | None = None


class CopyPlan(BaseModel):
    source_label: str
    destination_label: str
    tables: list[CopyTablePlan]
    never_copied: list[str]


class CopyTableReport(BaseModel):
    source: str
    target: str
    status: Literal["succeeded", "skipped", "failed"]
    rows_copied: int = 0
    carried: list[str] = Field(default_factory=list)
    not_carried: list[str] = Field(default_factory=list)
    message: str | None = None


class CopyReport(BaseModel):
    run_id: uuid.UUID
    status: Literal["succeeded", "failed"]
    tables: list[CopyTableReport]
    rows_copied: int
    never_copied: list[str]
