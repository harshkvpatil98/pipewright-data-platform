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


class DatasetVersionRead(BaseModel):
    """One immutable snapshot in a dataset's history (Phase 18, time travel)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    version_number: int
    content_hash: str | None
    file_name: str | None
    file_type: str | None
    row_count: int | None
    column_count: int | None
    pipeline_run_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    #: `active`, `pending_delete` (a retention sweep marked it; removal follows a
    #: grace period unless something pins it first) or `pruned` (data removed,
    #: this record kept as a tombstone).
    retention_state: str = "active"
    delete_after: datetime | None = None
    pruned_at: datetime | None = None
    #: Open pins holding this version (a rollback or replay in progress). A
    #: pinned version is never pruned.
    active_pins: int = 0


class DatasetVersionListResponse(BaseModel):
    #: Newest first, so the current head reads at the top.
    items: list[DatasetVersionRead]
    #: The head version number, or null for a dataset with no recorded history
    #: yet (materialised before versioning, or never materialised).
    current_version: int | None


class DatasetVersionDiffRequest(BaseModel):
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    #: Columns that uniquely identify a row in BOTH versions. Without them —
    #: or when they turn out not to be unique — the diff returns duplicate-aware
    #: added/removed counts and states that changed-row classification is
    #: unavailable (phase-18 decision #7: do not guess).
    identity_columns: list[str] = Field(default_factory=list, max_length=8)


class DatasetVersionDiff(BaseModel):
    dataset_id: uuid.UUID
    from_version: int
    to_version: int
    #: True when both versions carry the same content digest — the diff is
    #: answered from the hashes without reading either artifact.
    identical: bool
    rows_before: int | None = None
    rows_after: int | None = None
    columns_added: list[str] = Field(default_factory=list)
    columns_removed: list[str] = Field(default_factory=list)
    rows_added: int | None = None
    rows_removed: int | None = None
    #: Null whenever changed-classification is unavailable.
    rows_changed: int | None = None
    changed_available: bool = False
    #: Why changed-classification is unavailable, when it is.
    reason: str | None = None
    sample_added: list[dict[str, Any]] = Field(default_factory=list)
    sample_removed: list[dict[str, Any]] = Field(default_factory=list)
    sample_changed: list[dict[str, Any]] = Field(default_factory=list)
    cells_changed_by_column: dict[str, int] = Field(default_factory=dict)
    sample_limit: int = 20
    method: str = ""


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
