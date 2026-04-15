from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_auth.models import User
    from service_datasets.models import Dataset
    from service_pipeline_runs.models import PipelineRun
    from service_sources.models import Source
    from service_transformations.models import TransformationPipeline


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_name", "name"),
        Index("ix_projects_status", "status"),
        Index("ix_projects_owner_user_id", "owner_user_id"),
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    owner: Mapped[User | None] = relationship(back_populates="projects")
    sources: Mapped[list[Source]] = relationship(back_populates="project", passive_deletes=True)
    datasets: Mapped[list[Dataset]] = relationship(back_populates="project", passive_deletes=True)
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(back_populates="project", passive_deletes=True)
    transformation_pipelines: Mapped[list["TransformationPipeline"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
