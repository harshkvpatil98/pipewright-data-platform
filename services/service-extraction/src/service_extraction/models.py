from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExtractionConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved, credentialed connection to an external database."""

    __tablename__ = "extraction_connections"
    __table_args__ = (
        Index("ix_extraction_connections_project_id", "project_id"),
        Index("ix_extraction_connections_connector_type", "connector_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # Secret fields inside are encrypted at rest via shared_python.security.config_crypto.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A repeatable extraction definition plus its incremental load state."""

    __tablename__ = "extraction_jobs"
    __table_args__ = (
        Index("ix_extraction_jobs_project_id", "project_id"),
        Index("ix_extraction_jobs_connection_id", "connection_id"),
        Index("ix_extraction_jobs_target_dataset_id", "target_dataset_id"),
        Index("ix_extraction_jobs_project_enabled", "project_id", "enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_connections.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Either a discovered relation or an operator-authored read-only SELECT.
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="table")
    source_schema: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_table: Mapped[str | None] = mapped_column(String(320), nullable=True)
    query_sql: Mapped[str | None] = mapped_column(Text, nullable=True)

    load_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full_refresh")
    cursor_column: Mapped[str | None] = mapped_column(String(160), nullable=True)
    primary_key_columns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    max_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=1_000_000)
    #: Transformation steps applied at extraction ("shape at the source"): the
    #: pushable prefix runs in the source database, the rest here, before the
    #: dataset is written. Null or empty means a plain extract.
    steps_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Incremental state. Stored as text so one column serves timestamps and ids.
    watermark_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    watermark_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
