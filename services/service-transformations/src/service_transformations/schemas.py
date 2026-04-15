from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from service_datasets.schemas import DatasetDetailRead
from service_pipeline_runs.schemas import PipelineRunRead


class TransformationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_type: str
    config: dict[str, Any]


class TransformationPipelineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active"] = "draft"
    steps_json: list[dict[str, Any]] = Field(default_factory=list)


class TransformationPipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active"] | None = None
    steps_json: list[dict[str, Any]] | None = None


class TransformationPipelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    base_dataset_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    name: str
    description: str | None
    status: Literal["draft", "active"]
    steps_json: list[TransformationStep]
    step_count: int
    created_at: datetime
    updated_at: datetime


class TransformationPipelineListResponse(BaseModel):
    items: list[TransformationPipelineRead]


class TransformationPreviewRequest(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list)


class TransformationPreviewSchemaColumn(BaseModel):
    name: str
    inferred_type: str


class TransformationPreviewSchema(BaseModel):
    ordered_columns: list[str]
    columns: list[TransformationPreviewSchemaColumn]


class TransformationPreviewResponse(BaseModel):
    preview_rows: list[dict[str, Any]]
    preview_columns: list[str]
    row_count_before: int
    row_count_after: int
    column_count_before: int
    column_count_after: int
    schema_before: TransformationPreviewSchema
    schema_after: TransformationPreviewSchema
    warnings: list[str]


class TransformationRunResponse(BaseModel):
    run: PipelineRunRead
    dataset: DatasetDetailRead
