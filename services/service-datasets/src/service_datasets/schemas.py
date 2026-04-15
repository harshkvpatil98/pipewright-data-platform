from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source_id: uuid.UUID | None = None
    original_filename: str | None = Field(default=None, max_length=255)
    status: str = Field(default="registered", pattern=r"^(registered|processing|ready|failed)$")
    row_count: int | None = Field(default=None, ge=0)
    column_count: int | None = Field(default=None, ge=0)
    schema_snapshot: dict[str, Any] | None = None


class DatasetSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID | None
    uploaded_by_user_id: uuid.UUID | None
    pipeline_run_id: uuid.UUID | None
    parent_dataset_id: uuid.UUID | None
    created_from_pipeline_id: uuid.UUID | None
    name: str
    original_filename: str | None
    file_name: str | None
    file_type: str | None
    file_size_bytes: int | None
    is_derived: bool
    status: str
    ingestion_status: str
    row_count: int | None
    column_count: int | None
    created_at: datetime
    updated_at: datetime


class DatasetDetailRead(DatasetSummaryRead):
    schema_snapshot: dict[str, Any] | None
    schema_json: dict[str, Any] | None
    profile_json: dict[str, Any] | None
    preview_json: dict[str, Any] | None
    ingestion_error: str | None
    last_profiled_at: datetime | None


class DatasetListResponse(BaseModel):
    items: list[DatasetSummaryRead]


class DatasetPreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    columns: list[str]
    rows: list[dict[str, Any]]


class DatasetProfileResponse(BaseModel):
    dataset_id: uuid.UUID
    profile: dict[str, Any] | None


class DatasetAuditProject(BaseModel):
    id: uuid.UUID
    name: str


class DatasetAuditOwnership(BaseModel):
    uploaded_by_user_id: uuid.UUID | None


class DatasetAuditArtifact(BaseModel):
    file_name: str | None
    original_filename: str | None
    file_type: str | None
    file_size_bytes: int | None
    file_path: str | None = Field(
        default=None,
        description="Relative storage path when safe to display; omitted when absolute or unsafe.",
    )


class DatasetAuditMetrics(BaseModel):
    row_count: int | None
    column_count: int | None
    ingestion_status: str
    created_at: datetime
    updated_at: datetime
    last_profiled_at: datetime | None


class DatasetAuditProfileHighlights(BaseModel):
    duplicate_row_count: int | None
    duplicate_row_percentage: float | None
    completeness_score: float | None
    high_null_columns: list[str]
    constant_value_columns: list[str]
    potential_id_columns: list[str]


class DatasetAuditLineage(BaseModel):
    created_from_pipeline_id: uuid.UUID | None
    pipeline_run_id: uuid.UUID | None
    parent_dataset_id: uuid.UUID | None


class DatasetAuditSchemaSummary(BaseModel):
    column_count: int | None
    sample_column_names: list[str]


class DatasetAuditSummary(BaseModel):
    id: uuid.UUID
    name: str
    is_derived: bool
    parent_dataset_id: uuid.UUID | None
    project: DatasetAuditProject
    ownership: DatasetAuditOwnership
    artifact: DatasetAuditArtifact
    metrics: DatasetAuditMetrics
    profile_highlights: DatasetAuditProfileHighlights
    lineage: DatasetAuditLineage
    schema_summary: DatasetAuditSchemaSummary
    warnings: list[str]
