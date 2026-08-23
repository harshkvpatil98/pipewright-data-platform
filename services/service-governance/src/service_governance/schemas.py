"""Contracts for versions, approvals, the audit log, and comments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ResourceType = Literal["workflow", "pipeline", "quality_rule", "extraction_job"]
TargetType = Literal["dataset", "workflow", "pipeline", "run", "incident"]
ChangeStatus = Literal["open", "approved", "rejected", "withdrawn"]
Outcome = Literal["succeeded", "denied", "failed"]


class ChangeRead(BaseModel):
    path: str
    kind: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None


class SnapshotDiffRead(BaseModel):
    changes: list[ChangeRead]
    truncated: bool
    identical: bool
    summary: str


class VersionRead(BaseModel):
    id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID
    version: int
    name: str
    change_summary: str | None
    created_by_user_id: uuid.UUID | None
    created_by_username: str | None = None
    restored_from_version: int | None
    created_at: datetime


class VersionDetail(VersionRead):
    snapshot_json: dict[str, Any]


class VersionListResponse(BaseModel):
    items: list[VersionRead]
    resource_type: ResourceType
    resource_id: uuid.UUID


class VersionDiffResponse(BaseModel):
    left_version: int
    right_version: int
    diff: SnapshotDiffRead


class RestoreRequest(BaseModel):
    version: int = Field(ge=1)


class RestoreResponse(BaseModel):
    resource_type: ResourceType
    resource_id: uuid.UUID
    restored_from_version: int
    new_version: int
    summary: str


class ChangeRequestCreate(BaseModel):
    resource_type: ResourceType
    resource_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    after_json: dict[str, Any]


class ChangeRequestReview(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ChangeRequestRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID
    title: str
    description: str | None
    status: ChangeStatus
    change_summary: str | None
    requested_by_user_id: uuid.UUID | None
    requested_by_username: str | None = None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_by_username: str | None = None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class ChangeRequestDetail(ChangeRequestRead):
    before_json: dict[str, Any] | None
    after_json: dict[str, Any]
    diff: SnapshotDiffRead


class ChangeRequestListResponse(BaseModel):
    items: list[ChangeRequestRead]
    open_count: int


class AuditEntryRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_username: str | None
    method: str
    path: str
    action: str
    resource_type: str | None
    resource_id: str | None
    status_code: int
    outcome: Outcome
    correlation_id: str | None
    duration_ms: int | None
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditEntryRead]


class PromoteRequest(BaseModel):
    target_project_id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID


class UnresolvedReferenceRead(BaseModel):
    key: str
    value: str
    where: str


class PromoteResponse(BaseModel):
    source_project_id: uuid.UUID
    target_project_id: uuid.UUID
    resource_type: ResourceType
    new_resource_id: uuid.UUID
    unresolved: list[UnresolvedReferenceRead]
    summary: str


class CommentCreate(BaseModel):
    target_type: TargetType
    target_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


class CommentRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    target_type: TargetType
    target_id: uuid.UUID
    body: str
    author_user_id: uuid.UUID | None
    author_username: str | None = None
    mentions: list[str]
    resolved_at: datetime | None
    created_at: datetime


class CommentListResponse(BaseModel):
    items: list[CommentRead]
    open_count: int
