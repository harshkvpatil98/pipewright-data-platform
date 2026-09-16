from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from service_destinations.publish_schemas import DatasetPublishPostgresResponse
from service_pipeline_runs.schemas import PipelineRunRead
from service_transformations.schemas import TransformationRunResponse

ScheduleTypeLiteral = Literal[
    "transformation_pipeline_run",
    "postgres_publish",
    # The nightly connector schema watch. On the general scheduler rather
    # than a cron of its own: it needs the same claiming, retry and
    # timezone handling every other scheduled thing needs, and a second
    # scheduler is a second place for a job to silently stop running.
    "connector_schema_watch",
]


class ScheduledOperationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    schedule_type: ScheduleTypeLiteral
    cron_expression: str = Field(min_length=1, max_length=512)
    timezone: str | None = Field(default=None, max_length=64)
    enabled: bool = True
    target_config: dict[str, Any]


class ScheduledOperationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=512)
    timezone: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    target_config: dict[str, Any] | None = None


class ScheduleToggleRequest(BaseModel):
    enabled: bool


class ScheduledOperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    schedule_type: str
    cron_expression: str
    timezone: str | None
    enabled: bool
    target_config_json: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    last_triggered_at: datetime | None
    next_run_at: datetime | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_status: str | None
    last_error_message: str | None
    execution_count: int
    retry_count_current: int = Field(default=0)
    max_retries: int = Field(default=1)
    next_retry_at: datetime | None = Field(default=None)
    last_failure_at: datetime | None = Field(default=None)
    claim_owner_id: str | None = Field(default=None)
    claim_acquired_at: datetime | None = Field(default=None)
    claim_expires_at: datetime | None = Field(default=None)
    created_at: datetime
    updated_at: datetime


class ScheduledOperationListResponse(BaseModel):
    items: list[ScheduledOperationRead]


class ScheduleTriggerResponse(BaseModel):
    success: bool
    message: str
    schedule: ScheduledOperationRead
    triggered_run: PipelineRunRead | None = None
    transformation: TransformationRunResponse | None = None
    postgres_publish: DatasetPublishPostgresResponse | None = None


class RunDueSchedulesSummary(BaseModel):
    checked_count: int
    due_count: int
    triggered_count: int
    success_count: int
    failure_count: int
    affected_schedule_ids: list[uuid.UUID]


class SchedulerRuntimeStatusResponse(BaseModel):
    """Lightweight introspection for operators; not a full health dashboard."""

    internal_api_configured: bool
    scheduler_runtime_id_configured: bool
    total_schedules: int
    due_now_count: int
    lease_active_count: int
    stale_lease_count: int
    note: str
