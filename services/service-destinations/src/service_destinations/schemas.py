from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DestinationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    destination_type: str = Field(pattern=r"^(postgres|s3|local_export)$")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")
    config_json: dict[str, Any] = Field(default_factory=dict)


class DestinationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    config_json: dict[str, Any] | None = None


class DestinationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    destination_type: str
    status: str
    config_json: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DestinationListResponse(BaseModel):
    items: list[DestinationRead]


class DestinationTestResult(BaseModel):
    success: bool
    checked_at: datetime
    message: str
    latency_ms: float | None = None
    warnings: list[str] = Field(default_factory=list)
