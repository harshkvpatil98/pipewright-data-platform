"""Contracts for project membership."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["viewer", "operator", "editor", "admin"]


class MemberRead(BaseModel):
    id: uuid.UUID | None
    user_id: uuid.UUID
    username: str
    role: Role
    # True for the project's owner, who has no membership row to edit.
    is_owner: bool
    invited_by_username: str | None = None
    created_at: datetime | None = None


class MemberListResponse(BaseModel):
    items: list[MemberRead]
    # What the caller may do, so the UI can hide controls it would be told off for.
    your_role: Role


class MemberInvite(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    role: Role = "viewer"


class MemberRoleUpdate(BaseModel):
    role: Role


class RoleReference(BaseModel):
    role: Role
    description: str


class RoleCatalogResponse(BaseModel):
    items: list[RoleReference]
