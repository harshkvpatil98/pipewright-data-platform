from __future__ import annotations

import warnings

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# `schema_json` is this API's public field name and cannot change; pydantic
# warns because BaseModel still carries a deprecated method of the same name.
# The clash is upstream and cosmetic, so exactly that message is filtered.
warnings.filterwarnings(
    "ignore", message=r'Field name "schema_json".*', category=UserWarning
)



class DatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source_id: uuid.UUID | None = None
    original_filename: str | None = Field(default=None, max_length=255)
    status: str = Field(default="registered", pattern=r"^(registered|processing|ready|failed)$")
    row_count: int | None = Field(default=None, ge=0)
    column_count: int | None = Field(default=None, ge=0)
    schema_snapshot: dict[str, Any] | None = None


class DatasetUpdate(BaseModel):
    """What may be changed about a dataset once it is registered.

    Only the name, and deliberately. The rest of a dataset's record -- its row
    and column counts, its inferred schema, where its bytes are -- describes a
    file that was actually read. Letting those be edited would let the record
    disagree with the data it stands for, and every profile, rule and lineage
    edge downstream is derived from them.
    """

    name: str | None = Field(default=None, min_length=2, max_length=160)


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
    #: How this file was read: the delimiter, the header row, every column's
    #: type and date format. Exposed because "why is this column text" is a
    #: question somebody asks of the dataset, not of the upload screen they
    #: saw once. Null for datasets ingested before Phase 11.
    ingest_spec_json: dict[str, Any] | None = None


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
