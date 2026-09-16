from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from service_datasets.schemas import DatasetDetailRead
from service_pipeline_runs.schemas import PipelineRunRead


class IngestionUpload(BaseModel):
    file_name: str
    content_type: str
    file_bytes: bytes


class IngestionSchemaColumn(BaseModel):
    name: str
    inferred_type: str


class IngestionPreview(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


class IngestionProfileColumn(BaseModel):
    name: str
    inferred_type: str
    null_count: int
    null_percentage: float
    unique_count: int
    unique_percentage: float
    sample_values: list[Any]
    min_value: Any | None = None
    max_value: Any | None = None
    mean_value: float | None = None
    std_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    possible_identifier: bool = False
    mixed_type_suspected: bool = False


class IngestionProfile(BaseModel):
    row_count: int
    column_count: int
    duplicate_row_count: int
    duplicate_row_percentage: float
    total_null_cells: int
    completeness_score: float
    columns: list[IngestionProfileColumn]
    quality_flags: dict[str, list[str]]


class IngestionResult(BaseModel):
    dataset_id: uuid.UUID
    file_path: str
    file_name: str
    file_type: str
    file_size_bytes: int
    schema_json: dict[str, Any]
    profile_json: dict[str, Any]
    preview_json: dict[str, Any]
    row_count: int
    column_count: int


class DatasetUploadResponse(BaseModel):
    dataset: DatasetDetailRead
    run: PipelineRunRead


# ------------------------------------------------- Phase 11: analyse first


class AnalyseResponse(BaseModel):
    """What the sniff found, before anything is stored.

    `questions` is the field that matters: it holds the decisions the file
    genuinely does not settle -- an ambiguous date format, a separator that
    could be decimal or thousands -- and an upload proceeds only once they are
    answered. Everything else is inferred with a confidence the caller can see.
    """

    file_name: str
    file_size_bytes: int
    analysis: dict[str, Any]
    spec: dict[str, Any]
    preview: dict[str, Any]
    conversion_notes: list[str] = Field(default_factory=list)
    matched_spec: dict[str, Any] | None = None
    questions: list[dict[str, Any]] = Field(default_factory=list)


class IngestSpecRead(BaseModel):
    id: str
    label: str
    name_pattern: str
    column_fingerprint: str
    file_format: str
    spec: dict[str, Any]
    use_count: int
    last_used_at: str | None = None
    created_at: str | None = None


class IngestSpecListResponse(BaseModel):
    items: list[IngestSpecRead]


class RememberSpecRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    file_name: str = Field(min_length=1, max_length=300)
    spec: dict[str, Any]
    #: The columns this spec was confirmed against, for the fingerprint.
    columns: list[str] = Field(default_factory=list)


class UploadSessionRead(BaseModel):
    upload_id: str
    file_name: str
    total_bytes: int
    chunk_bytes: int
    expected_chunks: int
    received_chunks: list[int]
    missing_chunks: list[int]
    received_bytes: int
    complete: bool
    completed: bool
    expires_at: str
