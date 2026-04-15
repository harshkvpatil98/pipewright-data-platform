from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_auth.models import User
    from service_pipeline_runs.models import PipelineRun
    from service_projects.models import Project
    from service_sources.models import Source
    from service_transformations.models import TransformationPipeline


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_project_id", "project_id"),
        Index("ix_datasets_source_id", "source_id"),
        Index("ix_datasets_status", "status"),
        Index("ix_datasets_ingestion_status", "ingestion_status"),
        Index("ix_datasets_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_datasets_pipeline_run_id", "pipeline_run_id"),
        Index("ix_datasets_parent_dataset_id", "parent_dataset_id"),
        Index("ix_datasets_created_from_pipeline_id", "created_from_pipeline_id"),
        Index("ix_datasets_is_derived", "is_derived"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    parent_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    created_from_pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformation_pipelines.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    preview_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ingestion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_profiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="datasets")
    source: Mapped[Source | None] = relationship(back_populates="datasets")
    uploaded_by_user: Mapped[User | None] = relationship()
    pipeline_run: Mapped[PipelineRun | None] = relationship()
    parent_dataset: Mapped["Dataset | None"] = relationship(
        "Dataset",
        remote_side="Dataset.id",
        foreign_keys=[parent_dataset_id],
        back_populates="derived_datasets",
    )
    derived_datasets: Mapped[list["Dataset"]] = relationship(
        "Dataset",
        back_populates="parent_dataset",
        foreign_keys=[parent_dataset_id],
    )
    created_from_pipeline: Mapped["TransformationPipeline | None"] = relationship(
        "TransformationPipeline",
        foreign_keys=[created_from_pipeline_id],
        back_populates="derived_datasets",
    )
