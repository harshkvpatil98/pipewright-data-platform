from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PipelineRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    triggered_by_user_id: uuid.UUID
    pipeline_id: uuid.UUID | None = None
    triggered_by_username: str | None = None
    run_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    summary_json: dict[str, Any] | None
    logs_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class PipelineRunListResponse(BaseModel):
    items: list[PipelineRunRead]


class RunAuditHighlights(BaseModel):
    stage_count: int = 0
    failed_stage: str | None = None
    derived_dataset_created: bool = False
    ingestion_type: str | None = None
    transformation_type: str | None = None


class RunOutputVersion(BaseModel):
    """A version this run published -- the output pin (phase-18 §3). Resolves
    the run to what it produced, not to the dataset's later head."""

    dataset_id: uuid.UUID
    dataset_name: str | None = None
    version_number: int
    content_hash: str | None = None
    retention_state: str = "active"


class RunAuditSummary(BaseModel):
    id: uuid.UUID
    run_type: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    project_id: uuid.UUID
    triggered_by_user_id: uuid.UUID
    pipeline_id: uuid.UUID | None = None
    related_dataset_ids: list[uuid.UUID]
    summary_json: dict[str, Any] | None
    logs_json: dict[str, Any] | None
    highlights: RunAuditHighlights
    warnings: list[str]
    #: Versions published by this run, from the version table itself (every
    #: producer links its version to the run), so uploads and extractions have
    #: output pins too, not only transformations.
    output_versions: list[RunOutputVersion] = Field(default_factory=list)
    #: The recorded execution context (transformation runs since P7): frozen
    #: instant, semantic version, steps digest, input and output pins.
    execution_context: dict[str, Any] | None = None
    replayable: bool = False
    replay_reason: str | None = None
