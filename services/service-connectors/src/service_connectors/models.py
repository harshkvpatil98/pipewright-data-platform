"""What the schema watch remembers between runs.

Drift is a comparison, and a comparison needs something to compare against. The
sweep re-reads a connection's schema and holds it up against the last one it
saw, so exactly one row per (connection, stream) is stored: the *current*
answer, not a history.

That is deliberate. A history of schemas would be a second, worse copy of the
lineage the platform already derives, and the question the watch answers --
"has this changed since we last looked" -- needs one prior state, not all of
them. What did change, and when, is on the incident's timeline, which is where
somebody looking at a drift already is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConnectorSchemaSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The last schema seen for one stream of one configured connection."""

    __tablename__ = "connector_schema_snapshots"
    __table_args__ = (
        Index("ix_connector_schema_snapshots_project_id", "project_id"),
        # One row per stream, which is what makes the sweep idempotent: two
        # sweeps racing cannot produce two "last seen" answers that disagree.
        Index(
            "ix_connector_schema_snapshots_identity",
            "project_id",
            "connection_id",
            "stream_name",
            unique=True,
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: The extraction connection this was read through. Not a foreign key with
    #: a cascade, because a snapshot outliving its connection by a few seconds
    #: is harmless and a cascade across services is a coupling that is not.
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Column name -> the drift vocabulary's type name.
    columns_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: Whether the columns came from the source itself or from a manifest.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="declared")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The grading of the most recent comparison, so the watch view can be
    #: rendered without recomputing every sweep.
    last_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    last_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    drift_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
