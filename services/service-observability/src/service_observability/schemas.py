"""Contracts for metrics, anomalies, freshness, and incidents."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from service_observability.freshness import MAX_MAX_AGE_MINUTES, MIN_MAX_AGE_MINUTES

IncidentStatus = Literal["open", "acknowledged", "resolved"]
IncidentSeverity = Literal["low", "medium", "high", "critical"]
IncidentSource = Literal["quality", "drift", "freshness", "anomaly", "workflow"]
Sensitivity = Literal["low", "medium", "high"]


class MetricPoint(BaseModel):
    value: float
    captured_at: datetime
    logical_date: datetime | None = None
    workflow_run_id: uuid.UUID | None = None


class MetricSeries(BaseModel):
    metric_key: str
    column_name: str | None
    label: str
    unit: str | None
    points: list[MetricPoint]
    latest: float | None
    previous: float | None
    change_percentage: float | None


class MetricHistoryResponse(BaseModel):
    dataset_id: uuid.UUID
    series: list[MetricSeries]


class MetricCaptureResponse(BaseModel):
    dataset_id: uuid.UUID
    metrics_recorded: int
    captured_at: datetime


class AnomalyRead(BaseModel):
    metric_key: str
    column_name: str | None
    label: str
    value: float
    baseline: float | None
    score: float | None
    status: Literal["ok", "anomalous", "no_baseline"]
    direction: Literal["above", "below", "flat"]
    sample_size: int
    severity: IncidentSeverity
    explanation: str


class AnomalyScanResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    sensitivity: Sensitivity
    anomalies: list[AnomalyRead]
    checked_count: int
    summary: str


class FreshnessPolicyCreate(BaseModel):
    dataset_id: uuid.UUID
    max_age_minutes: int = Field(ge=MIN_MAX_AGE_MINUTES, le=MAX_MAX_AGE_MINUTES)
    severity: IncidentSeverity = "high"
    enabled: bool = True


class FreshnessPolicyUpdate(BaseModel):
    max_age_minutes: int | None = Field(default=None, ge=MIN_MAX_AGE_MINUTES, le=MAX_MAX_AGE_MINUTES)
    severity: IncidentSeverity | None = None
    enabled: bool | None = None


class FreshnessPolicyRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    max_age_minutes: int
    severity: IncidentSeverity
    enabled: bool
    last_checked_at: datetime | None
    last_status: str | None
    last_age_minutes: float | None
    created_at: datetime
    updated_at: datetime


class FreshnessPolicyListResponse(BaseModel):
    items: list[FreshnessPolicyRead]


class FreshnessCheckItem(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    status: Literal["fresh", "stale", "unknown"]
    age_minutes: float | None
    max_age_minutes: int
    overdue_minutes: float
    explanation: str
    incident_id: uuid.UUID | None = None


class FreshnessCheckResponse(BaseModel):
    checked: int
    stale: int
    incidents_opened: int
    incidents_resolved: int
    items: list[FreshnessCheckItem]


class IncidentEventRead(BaseModel):
    id: uuid.UUID
    sequence: int
    kind: str
    message: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None = None
    data_json: dict[str, Any] | None
    created_at: datetime


class IncidentRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    summary: str | None
    fingerprint: str
    source_kind: IncidentSource
    source_id: str | None
    severity: IncidentSeverity
    status: IncidentStatus
    dataset_id: uuid.UUID | None
    dataset_name: str | None = None
    workflow_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assignee_name: str | None = None
    opened_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_note: str | None
    occurrence_count: int
    context_json: dict[str, Any] | None


class IncidentDetail(IncidentRead):
    events: list[IncidentEventRead]


class IncidentListResponse(BaseModel):
    items: list[IncidentRead]
    open_count: int
    acknowledged_count: int
    resolved_count: int


class IncidentActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class IncidentAssignRequest(BaseModel):
    assignee_user_id: uuid.UUID | None = None


class IncidentCommentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
