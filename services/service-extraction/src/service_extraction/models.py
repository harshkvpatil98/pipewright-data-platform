from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
    #: source_kind "stream": what a non-SQL connector listed (name, namespace,
    #: kind, detail), or NULL to import everything the connection returns.
    stream_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

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


class StreamSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A live source: rows that arrive instead of being asked for (D1).

    `kind` is one of `service_extraction.live.KINDS`: a webhook (an address
    keyed by a token, hashed at rest), a database's change log (through a
    project connection, or its own settings) or a message queue (its own
    settings, secrets encrypted in `config_json`). The runner reads it every
    `read_every_seconds` into `stream_events`, saving `cursor` (the source's
    own position, JSON) in the same transaction, and saves its datasets every
    `save_every_seconds`: the log of every event (`dataset_id`), each followed
    table as it is now (`LiveTable`) and each live recipe's output.
    """

    __tablename__ = "stream_sources"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_stream_sources_token_hash"),
        Index("ix_stream_sources_project_id", "project_id"),
        Index("ix_stream_sources_due", "status", "next_read_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: `active`, `paused`, or `failing` (still read, backing off).
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_connections.id", ondelete="SET NULL"), nullable=True
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: The source's own position as JSON, saved with the events it ends.
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    #: Every event ever stored; also where the next event's `seq` comes from.
    events_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_materialised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    read_every_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    save_every_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    keep_events_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=168, server_default="168")
    next_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Failed passes in a row; the owner is told once at five.
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Events up to this `seq` are in the log dataset.
    log_saved_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Events waiting at the source when it last said, or None when it cannot say.
    behind: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    claim_owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StreamEvent(UUIDPrimaryKeyMixin, Base):
    """One thing that arrived: a post, a message or one row change.

    `seq` orders events within a source. `position` is the source's own id
    for it (an offset, a sequence number, a message id, a digest of a change's
    LSN) and is unique within the source, so storing one again is refused;
    None when the source gives nothing to recognise a repeat by.
    """

    __tablename__ = "stream_events"
    __table_args__ = (
        UniqueConstraint("source_id", "seq", name="uq_stream_events_source_seq"),
        UniqueConstraint("source_id", "position", name="uq_stream_events_source_position"),
        Index("ix_stream_events_source_id", "source_id", "seq"),
        Index("ix_stream_events_received", "source_id", "received_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_sources.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    #: `webhook` or `message`, or `insert`, `update`, `delete` for a row change.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    table_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    position: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LiveTable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A table a change-capture source keeps current as a dataset (D1, L1).

    `state`: `waiting` (snapshot not taken), `snapshot` (being read),
    `following` (applying changes by `key_columns_json`), `log_only` (no
    primary key, so only its changes are kept) or `failed`. Changes up to
    `applied_seq` are in the dataset's current version.
    """

    __tablename__ = "stream_tables"
    __table_args__ = (UniqueConstraint("source_id", "table_name", name="uq_stream_tables_source_table"),)

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_sources.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(320), nullable=False)
    key_columns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="waiting", server_default="waiting")
    snapshot_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_now: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LiveRecipe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recipe that runs on a live source's events as they arrive (D1, L4).

    Row-by-row steps from a saved recipe, an optional lookup in a dataset,
    and an optional summary by time window. `state_json` (open windows, the
    watermark) and `processed_seq` are saved in the same transaction as the
    results they produced, so a repeated batch never counts an event twice.
    """

    __tablename__ = "live_recipes"
    __table_args__ = (Index("ix_live_recipes_source", "source_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_sources.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformation_pipelines.id", ondelete="SET NULL"), nullable=True
    )
    lookup_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    window_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    group_by_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    measures_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    output_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    processed_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Without a window: events up to here are in the output dataset.
    saved_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    late_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    late_restated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    without_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unmatched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    events_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    results_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class LiveRecipeResult(UUIDPrimaryKeyMixin, Base):
    """One window's measures for one group (D1, L4). Final once the watermark
    passes the window's end; `restated` counts late events that changed it after."""

    __tablename__ = "live_recipe_results"
    __table_args__ = (
        UniqueConstraint("live_recipe_id", "window_start", "window_end", "group_key", name="uq_live_recipe_results_window"),
        Index("ix_live_recipe_results_end", "live_recipe_id", "window_end"),
    )

    live_recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_recipes.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False)
    group_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    restated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
