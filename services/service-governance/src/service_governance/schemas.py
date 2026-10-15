"""Contracts for versions, approvals, the audit log, and comments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ResourceType = Literal["workflow", "pipeline", "quality_rule", "extraction_job", "metric"]
TargetType = Literal[
    "dataset", "workflow", "pipeline", "run", "incident", "change_request", "dashboard", "chart"
]
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
    #: What it did, in words, and the name of what it touched while that still exists.
    summary: str = ""
    object_name: str | None = None
    #: The API token it came with (X2); None for a person signed in.
    credential: str | None = None


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


class CellAnchor(BaseModel):
    """The cell a thread is about, on a dataset (C2).

    The row is named by its identifier column's value when the dataset has
    one, which survives new versions; otherwise by its number in one
    version, which is only that version's row.
    """

    column: str = Field(min_length=1, max_length=200)
    row_key_column: str | None = Field(default=None, min_length=1, max_length=200)
    row_key_value: str | None = Field(default=None, max_length=500)
    row_number: int | None = Field(default=None, ge=1)
    version: int | None = Field(default=None, ge=1)


class CommentCreate(BaseModel):
    target_type: TargetType
    target_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)
    #: The comment this replies to; a reply to a reply joins the same thread.
    parent_id: uuid.UUID | None = None
    #: The cell a new thread on a dataset is about.
    anchor: CellAnchor | None = None
    #: The step a new thread on a recipe is about (E1), by the step's id.
    step_id: str | None = Field(default=None, min_length=1, max_length=64)


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
    resolved_by_username: str | None = None
    created_at: datetime
    parent_id: uuid.UUID | None = None
    anchor: CellAnchor | None = None
    step_id: str | None = None
    #: On a thread's first comment, the replies to it, oldest first.
    replies: list["CommentRead"] = Field(default_factory=list)


class CommentListResponse(BaseModel):
    #: Threads: each first comment with its replies.
    items: list[CommentRead]
    open_count: int


class PresenceUpdate(BaseModel):
    target_type: Literal["recipe"]
    target_id: uuid.UUID
    client_id: str = Field(min_length=1, max_length=64)
    #: What in it this person has open, such as {"step": "<step id>"}.
    focus: dict[str, str] | None = None


class PresencePerson(BaseModel):
    user_id: uuid.UUID
    name: str
    initials: str
    #: Which of eight colours marks them, the same everywhere.
    colour: int
    focus: dict[str, str] | None
    you: bool
    client_id: str


class PresenceResponse(BaseModel):
    people: list[PresencePerson]
