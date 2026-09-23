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
        Index("ix_dataset_versions_retention_state", "retention_state"),
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
    #: The preview snapshot captured when this version was published, so a
    #: temporal read shows the data as it was then. Null for a version recorded
    #: before this column existed.
    preview_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # -- retention lifecycle (§4 of the accepted requirements) -----------------
    #: `active` (readable, prunable once superseded) → `pending_delete` (a sweep
    #: marked it; `delete_after` is the lease before anything is removed) →
    #: `pruned` (metadata kept as a tombstone, data removed). These are
    #: lifecycle columns, not history: the snapshot's content and number are
    #: never rewritten by them.
    retention_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set when the bytes are actually gone. A pruned row with this null is a
    #: sweep that crashed between metadata and blob deletion, and is resumed.
    artifact_removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    dataset: Mapped[Dataset] = relationship("Dataset", back_populates="versions")
    pins: Mapped[list["DatasetVersionPin"]] = relationship(
        "DatasetVersionPin", back_populates="version", cascade="all, delete-orphan"
    )


class DatasetVersionPin(UUIDPrimaryKeyMixin, Base):
    """Somebody holding a version open: a rollback copying its bytes, a replay
    reading it as a pinned input.

    The pin is written and COMMITTED before the holder reads any bytes (§4: a
    pin is durable before the read, never relied on while uncommitted), so a
    retention sweep in another session sees it and leaves the version alone.
    `released_at` closes it; a holder that crashes leaves an open pin, which is
    the safe failure -- data kept, not lost.
    """

    __tablename__ = "dataset_version_pins"
    __table_args__ = (
        Index("ix_dataset_version_pins_version_id", "dataset_version_id"),
        Index("ix_dataset_version_pins_holder", "holder_kind", "holder_id"),
    )

    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: What kind of thing holds it: `rollback`, `replay`, `run`.
    holder_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The holder's own id (a pipeline run, usually), for release and audit.
    holder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    version: Mapped[DatasetVersion] = relationship("DatasetVersion", back_populates="pins")
