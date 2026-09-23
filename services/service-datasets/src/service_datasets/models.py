from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
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
    #: How this file was read: the delimiter, the header row, every column's
    #: type and date format. Kept with the dataset so "why is this column text"
    #: has an answer, and so the same file can be re-read the same way.
    #: Null for datasets ingested before Phase 11 -- inventing one would be a
    #: claim about how they were read.
    ingest_spec_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

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
    versions: Mapped[list["DatasetVersion"]] = relationship(
        "DatasetVersion",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetVersion.version_number",
    )


class DatasetVersion(UUIDPrimaryKeyMixin, Base):
    """One immutable snapshot published when a dataset was materialised.

    Time travel (Phase 18) is built on these rows. Each successful
    materialisation appends one -- `version_number` is 1-based and monotonic per
    dataset, so the highest is the current head -- and a version is never updated
    or renumbered (settled decision #6: even a rollback appends a new version, it
    does not rewrite history). `file_path` points at the bytes that version
    published; because every producer writes a uuid-keyed path, that artifact is
    not overwritten by a later materialisation, so the pointer stays valid.

    There is deliberately no `updated_at`: an immutable record has no update.
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (
        Index("ix_dataset_versions_dataset_id", "dataset_id"),
        Index("ix_dataset_versions_content_hash", "content_hash"),
        # Two versions of one dataset can never share a number, even under a
        # concurrent double-publish -- the database refuses the second insert.
        UniqueConstraint(
            "dataset_id", "version_number", name="uq_dataset_versions_dataset_number"
        ),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: `sha256:<hex>` of the published bytes; null only for a version recorded
    #: without the bytes in hand. Same digest means same data.
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="versions")
