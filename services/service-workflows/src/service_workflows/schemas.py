from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from service_workflows.graph import EDGE_CONDITIONS, NODE_KEY_PATTERN, NODE_TYPES

_NODE_TYPE_PATTERN = "^(" + "|".join(NODE_TYPES) + ")$"
_CONDITION_PATTERN = "^(" + "|".join(EDGE_CONDITIONS) + ")$"


class WorkflowNodeInput(BaseModel):
    node_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    node_type: str = Field(pattern=_NODE_TYPE_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)
    continue_on_failure: bool = False
    position_x: float = 0.0
    position_y: float = 0.0

    @model_validator(mode="after")
    def _validate_key(self) -> WorkflowNodeInput:
        if not NODE_KEY_PATTERN.match(self.node_key):
            raise ValueError(
                "node_key must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            )
        return self


class WorkflowEdgeInput(BaseModel):
    from_node_key: str = Field(min_length=1, max_length=64)
    to_node_key: str = Field(min_length=1, max_length=64)
    condition: str = Field(default="on_success", pattern=_CONDITION_PATTERN)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    trigger_type: str = Field(default="manual", pattern="^(manual|cron)$")
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    nodes: list[WorkflowNodeInput] = Field(default_factory=list)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cron_needs_expression(self) -> WorkflowCreate:
        if self.trigger_type == "cron" and not (self.cron_expression or "").strip():
            raise ValueError("cron_expression is required when trigger_type is 'cron'.")
        return self


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    trigger_type: str | None = Field(default=None, pattern="^(manual|cron)$")
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    default_parameters: dict[str, Any] | None = None
    # Supplying either replaces the whole graph, which keeps the canvas's
    # save-everything model simple and atomic.
    nodes: list[WorkflowNodeInput] | None = None
    edges: list[WorkflowEdgeInput] | None = None


class WorkflowNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_key: str
    name: str
    node_type: str
    config_json: dict[str, Any]
    continue_on_failure: bool
    position_x: float
    position_y: float


class WorkflowEdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_node_key: str
    to_node_key: str
    condition: str


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    trigger_type: str
    cron_expression: str | None
    timezone: str | None
    next_run_at: datetime | None
    default_parameters: dict[str, Any] | None
    last_run_at: datetime | None
    last_run_status: str | None
    execution_count: int
    created_at: datetime
    updated_at: datetime


class WorkflowDetail(WorkflowRead):
    nodes: list[WorkflowNodeRead] = Field(default_factory=list)
    edges: list[WorkflowEdgeRead] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    execution_order: list[list[str]] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    items: list[WorkflowRead]


class WorkflowNodeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_key: str
    node_name: str
    node_type: str
    status: str
    sequence: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    output_json: dict[str, Any] | None
    message: str | None
    skip_reason: str | None
    pipeline_run_id: uuid.UUID | None


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    trigger: str
    logical_date: datetime | None
    parameters_json: dict[str, Any] | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    nodes_total: int
    nodes_succeeded: int
    nodes_failed: int
    nodes_skipped: int
    created_at: datetime


class TimelineEntryRead(BaseModel):
    node_key: str
    node_name: str
    node_type: str
    status: str
    offset_ms: int
    duration_ms: int
    share_percentage: float


class RunTimelineRead(BaseModel):
    total_ms: int
    entries: list[TimelineEntryRead] = Field(default_factory=list)
    slowest_node_key: str | None = None
    summary: str


class WorkflowRunDetail(WorkflowRunRead):
    node_runs: list[WorkflowNodeRunRead] = Field(default_factory=list)
    timeline: RunTimelineRead | None = None


class NodeDiffRead(BaseModel):
    node_key: str
    node_name: str
    node_type: str
    left_status: str | None
    right_status: str | None
    left_duration_ms: int | None
    right_duration_ms: int | None
    duration_change_percentage: float | None
    verdict: str
    changes: list[str] = Field(default_factory=list)


class RunDiffResponse(BaseModel):
    left_run_id: uuid.UUID
    right_run_id: uuid.UUID
    left: WorkflowRunRead
    right: WorkflowRunRead
    nodes: list[NodeDiffRead] = Field(default_factory=list)
    summary: str
    identical: bool


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunRead]


class WorkflowRunRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class WorkflowValidationResponse(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    execution_order: list[list[str]] = Field(default_factory=list)


class WorkerTickResponse(BaseModel):
    """Result of asking a worker to process the queue once."""

    runs_processed: int
    run_ids: list[uuid.UUID] = Field(default_factory=list)
    queue_depth: int


class BackfillRequest(BaseModel):
    """Replay a workflow across a past date range, one run per slot."""

    start: datetime
    end: datetime
    interval: str = Field(default="daily", pattern="^(hourly|daily|weekly|monthly)$")
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _range_is_forward(self) -> BackfillRequest:
        if self.end <= self.start:
            raise ValueError("end must be after start.")
        return self


class BackfillPreviewResponse(BaseModel):
    """What a backfill would do, without queuing anything."""

    interval: str
    slot_count: int
    first_slot: datetime | None = None
    last_slot: datetime | None = None
    sample_slots: list[datetime] = Field(default_factory=list)


class BackfillResponse(BaseModel):
    interval: str
    runs_queued: int
    run_ids: list[uuid.UUID] = Field(default_factory=list)
    first_slot: datetime | None = None
    last_slot: datetime | None = None


class MacroReference(BaseModel):
    """A macro operators can use in node configuration."""

    token: str
    description: str
    example: str | None = None


class MacroCatalogResponse(BaseModel):
    items: list[MacroReference]
