"""Contracts for tenancy, security policies, retention, usage, and SSO."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from service_enterprise.retention import MAX_RETAIN_DAYS, MIN_RETAIN_DAYS

ColumnAction = Literal["allow", "mask", "hash", "redact", "deny"]
ProjectRole = Literal["viewer", "operator", "editor", "admin"]
ErasureKind = Literal["email", "phone", "id", "name"]


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    plan: str = Field(default="standard", max_length=32)
    max_projects: int | None = Field(default=None, ge=1)
    max_datasets: int | None = Field(default=None, ge=1)


class OrganisationUpdate(BaseModel):
    """Rename a tenant, or adjust its plan and limits. Unset fields are left alone."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    plan: str | None = Field(default=None, max_length=32)
    max_projects: int | None = Field(default=None, ge=1)
    max_datasets: int | None = Field(default=None, ge=1)


class OrganisationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    max_projects: int | None
    max_datasets: int | None
    is_active: bool
    project_count: int = 0
    member_count: int = 0
    created_at: datetime


class OrganisationListResponse(BaseModel):
    items: list[OrganisationRead]


class LimitsResponse(BaseModel):
    limited: bool
    organisation: str | None = None
    plan: str | None = None
    projects: dict[str, Any] | None = None
    datasets: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    reason: str | None = None


class RowRuleInput(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    operator: str = "equals"
    value: Any = None


class ColumnRuleInput(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    action: ColumnAction = "mask"


class PolicyCreate(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    role: ProjectRole
    row_rules: list[RowRuleInput] = Field(default_factory=list, max_length=20)
    column_rules: list[ColumnRuleInput] = Field(default_factory=list, max_length=100)
    enabled: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    row_rules: list[RowRuleInput] | None = None
    column_rules: list[ColumnRuleInput] | None = None
    enabled: bool | None = None


class PolicyRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    role: ProjectRole
    row_rules: list[RowRuleInput]
    column_rules: list[ColumnRuleInput]
    enabled: bool
    created_at: datetime


class PolicyListResponse(BaseModel):
    items: list[PolicyRead]
    warnings: list[str] = Field(default_factory=list)


class PolicyPreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    role: ProjectRole
    # Set when the preview was run as a specific person rather than a bare role,
    # so the UI can say "viewing as dana (viewer)".
    viewed_as_username: str | None = None
    rows_before: int
    rows_after: int
    rows_hidden: int
    columns_masked: list[str]
    columns_removed: list[str]
    policies_applied: list[str]
    restricted: bool
    summary: str
    sample_rows: list[dict[str, Any]]


class RetentionCreate(BaseModel):
    resource_type: str = Field(min_length=1, max_length=32)
    retain_days: int = Field(ge=MIN_RETAIN_DAYS, le=MAX_RETAIN_DAYS)
    enabled: bool = True
    dry_run: bool = True


class RetentionRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    resource_type: str
    resource_label: str
    retain_days: int
    enabled: bool
    dry_run: bool
    last_run_at: datetime | None
    last_deleted_count: int


class RetentionListResponse(BaseModel):
    items: list[RetentionRead]
    retainable: dict[str, str]


class RetentionRunResponse(BaseModel):
    plans: list[dict[str, Any]]
    total_matched: int
    total_deleted: int
    summary: str


class ErasureCreate(BaseModel):
    subject_value: str = Field(min_length=1, max_length=320)
    subject_kind: ErasureKind = "email"
    # Searching is safe; redacting is not, so it is opt-in per request.
    apply: bool = False


class ErasureRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    subject_kind: ErasureKind
    status: str
    datasets_searched: int
    rows_affected: int
    report: dict[str, Any] | None
    completed_at: datetime | None
    created_at: datetime


class ErasureListResponse(BaseModel):
    items: list[ErasureRead]


class UsageResponse(BaseModel):
    period_days: int
    since: datetime
    totals: list[dict[str, Any]]
    rows_processed: int
    compute_seconds: float
    bytes_written: int
    summary: str


class SsoStatusResponse(BaseModel):
    oidc_configured: bool
    issuer: str | None
    saml: dict[str, Any]
    note: str
