from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

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
