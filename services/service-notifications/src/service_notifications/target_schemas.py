from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExternalNotificationTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    target_type: str
    enabled: bool = True
    config_json: dict[str, Any]
    subscribed_event_types: list[str]


class ExternalNotificationTargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool | None = None
    config_json: dict[str, Any] | None = None
    subscribed_event_types: list[str] | None = None


class ExternalNotificationTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    target_type: str
    enabled: bool
    config_json: dict[str, Any]
    subscribed_event_types: list[str]
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExternalNotificationTargetListResponse(BaseModel):
    items: list[ExternalNotificationTargetRead]


class ExternalNotificationTargetTestResponse(BaseModel):
    success: bool
    message: str
