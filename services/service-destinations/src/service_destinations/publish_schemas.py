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


class DeliveryRequest(BaseModel):
    """Deliver a dataset to a destination: a table (databases) or a file (storage)."""

    destination_id: uuid.UUID
    #: replace, append, or update matching rows (databases only).
    mode: Literal["replace", "append", "update"] = "replace"
    table_name: str | None = Field(default=None, max_length=64)
    key_columns: list[str] = Field(default_factory=list)
    file_name: str | None = Field(default=None, max_length=255)
    file_format: Literal["csv", "parquet"] = "csv"


class DeliveryColumn(BaseModel):
    name: str
    source: str
    type: str
    key: bool = False


class DeliveryPreview(BaseModel):
    destination_id: uuid.UUID
    destination_name: str
    destination_label: str
    kind: Literal["table", "file"]
    target: str
    mode: str
    rows: int
    columns: list[DeliveryColumn]
    notes: list[str]


class DeliveryResult(BaseModel):
    run_id: uuid.UUID
    # "queued": a large dataset the background worker is writing; follow the run.
    status: Literal["succeeded", "failed", "queued"]
    target: str
    mode: str
    message: str
    rows_written: int
    rows_updated: int
    rows_added: int
    table_created: bool | None = None
    warnings: list[str] = Field(default_factory=list)
