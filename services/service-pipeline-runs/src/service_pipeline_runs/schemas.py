from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
