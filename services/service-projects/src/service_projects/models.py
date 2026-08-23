from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
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
    # Indexed via the explicit Index above; `index=True` here would declare a
    # second index under the same name, which breaks metadata.create_all().
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    # Which copy of the world this project is. Environments are separate
    # projects rather than a flag on each resource: anything else means every
    # query in the platform has to remember to filter by environment, and the
    # one that forgets is the one that publishes test data to production.
    environment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="development"
    )
    # When true, edits to versioned resources must be proposed and reviewed
    # rather than applied directly.
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promoted_from_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    # Which tenant owns this project. Null on a single-tenant deployment.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    owner: Mapped[User | None] = relationship(back_populates="projects")
    sources: Mapped[list[Source]] = relationship(back_populates="project", passive_deletes=True)
    datasets: Mapped[list[Dataset]] = relationship(back_populates="project", passive_deletes=True)
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(back_populates="project", passive_deletes=True)
    transformation_pipelines: Mapped[list["TransformationPipeline"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
