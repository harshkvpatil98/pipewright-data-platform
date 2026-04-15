from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_datasets.models import Dataset
    from service_projects.models import Project


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_project_id", "project_id"),
        Index("ix_sources_source_type", "source_type"),
        Index("ix_sources_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project] = relationship(back_populates="sources")
    datasets: Mapped[list[Dataset]] = relationship(back_populates="source")
