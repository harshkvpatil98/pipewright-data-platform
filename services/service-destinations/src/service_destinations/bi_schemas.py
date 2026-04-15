from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BiIntegrationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    integration_type: str = Field(pattern=r"^(power_bi|tableau)$")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")
    config_json: dict[str, Any] = Field(default_factory=dict)


class BiIntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    config_json: dict[str, Any] | None = None


class BiIntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    integration_type: str
    status: str
    config_json: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class BiIntegrationListResponse(BaseModel):
    items: list[BiIntegrationRead]


class BiMetadataItem(BaseModel):
    id: str
    name: str


class BiConnectionMetadataResponse(BaseModel):
    integration_type: str
    metadata_kind: str
    items: list[BiMetadataItem]
