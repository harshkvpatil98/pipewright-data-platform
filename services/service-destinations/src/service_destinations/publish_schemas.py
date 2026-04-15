from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from service_pipeline_runs.schemas import PipelineRunRead


class DatasetPublishPostgresRequest(BaseModel):
    destination_id: uuid.UUID
    table_name: str = Field(..., min_length=1, max_length=63)
    write_mode: Literal["replace", "append"]


class DatasetPublishPowerBiRequest(BaseModel):
    connection_id: uuid.UUID
    workspace_id: uuid.UUID
    target_dataset_name: str = Field(..., min_length=1, max_length=200)
    target_table_name: str | None = Field(default=None, min_length=1, max_length=63)
    write_mode: Literal["replace", "append"]


class BiConnectionPublishSummary(BaseModel):
    id: uuid.UUID
    name: str
    integration_type: str


class DatasetPublishTableauRequest(BaseModel):
    connection_id: uuid.UUID
    tableau_project_id: uuid.UUID
    datasource_name: str = Field(..., min_length=1, max_length=200)
    write_mode: Literal["replace", "create_only"]


class DatasetPublishTableauResponse(BaseModel):
    success: bool
    message: str
    run: PipelineRunRead
    connection: BiConnectionPublishSummary
    tableau_site_id: str | None = None
    tableau_project_id: uuid.UUID
    datasource_name: str
    write_mode: str
    row_count_published: int | None = None
    row_count_attempted: int | None = None
    tableau_datasource_id: str | None = None
    provider_outcome: str | None = None
    summary_json: dict[str, Any] | None = None


class DatasetPublishPowerBiResponse(BaseModel):
    success: bool
    message: str
    run: PipelineRunRead
    connection: BiConnectionPublishSummary
    workspace_id: uuid.UUID
    target_dataset_name: str
    target_table_name: str
    write_mode: str
    row_count_published: int | None = None
    row_count_attempted: int | None = None
    power_bi_dataset_id: str | None = None
    provider_outcome: str | None = None
    summary_json: dict[str, Any] | None = None


class DestinationPublishSummary(BaseModel):
    id: uuid.UUID
    name: str
    destination_type: str


class DatasetPublishPostgresResponse(BaseModel):
    success: bool
    message: str
    run: PipelineRunRead
    target_table: str
    target_schema: str | None = None
    write_mode: str
    row_count_written: int | None = None
    row_count_attempted: int | None = None
    destination: DestinationPublishSummary
    summary_json: dict[str, Any] | None = None
