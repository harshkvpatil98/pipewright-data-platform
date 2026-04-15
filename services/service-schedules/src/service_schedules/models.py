from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduledOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Saved schedule definition with optional automatic execution via the due-schedule executor."""

    __tablename__ = "scheduled_operations"
    __table_args__ = (
        Index("ix_scheduled_operations_project_id", "project_id"),
        Index("ix_scheduled_operations_schedule_type", "schedule_type"),
        Index("ix_scheduled_operations_enabled", "enabled"),
        Index("ix_scheduled_operations_enabled_next_run", "enabled", "next_run_at"),
        Index("ix_scheduled_operations_enabled_next_retry", "enabled", "next_retry_at"),
        Index("ix_scheduled_operations_claim_expires_at", "claim_expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(512), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    target_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
