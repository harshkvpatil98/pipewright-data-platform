from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SchemaDriftComparisonResponse(BaseModel):
    dataset_id: uuid.UUID
    baseline_dataset_id: uuid.UUID
    severity: str
    has_drift: bool
    added_columns: list[str] = Field(default_factory=list)
    removed_columns: list[str] = Field(default_factory=list)
    type_changes: list[dict[str, Any]] = Field(default_factory=list)
    reordered: bool = False
    summary: str


class SchemaDriftEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID | None
    previous_dataset_id: uuid.UUID | None
    extraction_job_id: uuid.UUID | None
    severity: str
    summary: str
    added_columns: list[str] | None
    removed_columns: list[str] | None
    type_changes: list[dict[str, Any]] | None
    acknowledged: bool
    acknowledged_at: datetime | None
    created_at: datetime


class SchemaDriftEventListResponse(BaseModel):
    items: list[SchemaDriftEventRead]
