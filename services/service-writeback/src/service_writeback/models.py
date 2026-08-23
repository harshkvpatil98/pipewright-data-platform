"""Persisted change sets.

Staged rather than applied, so a change can be reviewed, shared with a
colleague, sent through the approval flow, and discarded -- none of which is
possible if an edit goes straight to the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: draft      -- being edited, nothing written
#: pending    -- submitted for approval
#: committed  -- applied successfully
#: failed     -- a commit was attempted and rolled back
#: discarded  -- abandoned
CHANGE_SET_STATUSES = ("draft", "pending", "committed", "failed", "discarded")


class ChangeSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "writeback_change_sets"
    __table_args__ = (
        Index("ix_writeback_change_sets_project_id", "project_id"),
        Index("ix_writeback_change_sets_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: The extraction connection this writes through.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extraction_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    table_schema: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled change")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    committed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rows_affected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Why a commit failed, kept so somebody can act on it later.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The statements as executed, recorded for the audit trail. Direct writes
    #: to a production table without one would be the worst thing this could ship.
    executed_sql: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: Columns the user designated as the row key, when the table has none.
    designated_key: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    edits: Mapped[list["ChangeSetEdit"]] = relationship(
        back_populates="change_set",
        cascade="all, delete-orphan",
        order_by="ChangeSetEdit.sequence",
    )


class ChangeSetEdit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "writeback_change_set_edits"
    __table_args__ = (
        Index("ix_writeback_change_set_edits_change_set_id", "change_set_id"),
    )

    change_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("writeback_change_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Order within the change set. Explicit, because `created_at` defaults to
    #: the transaction time in Postgres and every edit in one request ties.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    change_set: Mapped[ChangeSet] = relationship(back_populates="edits")
