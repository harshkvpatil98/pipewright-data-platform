from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, JSON, String, Text
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
    from service_projects.models import Project


class TransformationPipeline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = 'transformation_pipelines'
    __table_args__ = (
        Index('ix_transformation_pipelines_project_id', 'project_id'),
        Index('ix_transformation_pipelines_base_dataset_id', 'base_dataset_id'),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    base_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='draft')
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    project: Mapped[Project] = relationship(back_populates='transformation_pipelines')
    base_dataset: Mapped[Dataset] = relationship('Dataset', foreign_keys=[base_dataset_id])
    created_by_user: Mapped[User | None] = relationship()
    derived_datasets: Mapped[list[Dataset]] = relationship(
        'Dataset',
        back_populates='created_from_pipeline',
        foreign_keys='Dataset.created_from_pipeline_id',
    )
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(
        'PipelineRun',
        back_populates='transformation_pipeline',
        foreign_keys='PipelineRun.pipeline_id',
    )
