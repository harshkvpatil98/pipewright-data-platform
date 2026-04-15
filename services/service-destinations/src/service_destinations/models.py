from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DestinationConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "destination_configs"
    __table_args__ = (
        Index("ix_destination_configs_project_id", "project_id"),
        Index("ix_destination_configs_destination_type", "destination_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
