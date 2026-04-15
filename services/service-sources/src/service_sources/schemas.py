from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source_type: str = Field(pattern=r"^(csv|excel|json|api|postgres|s3)$")
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="active", pattern=r"^(active|pending|disabled)$")
    config_json: dict[str, Any] = Field(default_factory=dict)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    source_type: str
    description: str | None
    status: str
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    items: list[SourceRead]
