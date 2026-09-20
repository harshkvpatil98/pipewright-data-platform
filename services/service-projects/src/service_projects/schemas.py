from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="active", pattern=r"^(active|draft|archived)$")
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=180,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class ProjectUpdate(BaseModel):
    """What may be changed about a project after it exists.

    Every field is optional and the caller's *unset* fields are left alone, so
    renaming a project cannot blank its description by omission. `description`
    is nullable on purpose: passing an explicit null clears it, which is a
    different request from not mentioning it at all.

    The slug is absent deliberately. It is the stable name this project is
    referred to by, and rewriting it when the display name changes would break
    every link and bookmark pointing at the old one.
    """

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern=r"^(active|draft|archived)$")


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_user_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None
    status: str
    environment: str = "development"
    requires_approval: bool = False
    promoted_from_project_id: uuid.UUID | None = None
    source_count: int = 0
    dataset_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]


class ProjectDetail(ProjectSummary):
    pass
