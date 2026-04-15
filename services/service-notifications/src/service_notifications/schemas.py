from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    type: str
    level: str
    title: str
    message: str
    related_run_id: uuid.UUID | None
    related_schedule_id: uuid.UUID | None
    related_dataset_id: uuid.UUID | None
    related_pipeline_id: uuid.UUID | None
    is_read: bool
    created_at: datetime
    updated_at: datetime
    read_at: datetime | None


class UserNotificationListResponse(BaseModel):
    items: list[UserNotificationRead]
    unread_count: int


class MarkNotificationReadResponse(BaseModel):
    notification: UserNotificationRead


class MarkAllNotificationsReadResponse(BaseModel):
    updated_count: int
