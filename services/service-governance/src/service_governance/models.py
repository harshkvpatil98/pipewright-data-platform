from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ResourceVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A snapshot of one resource as it was after one edit.

    Stored whole rather than as a delta. Deltas are smaller and reconstructing
    a version from them is a chain that breaks the moment one link is wrong --
    which is exactly the moment somebody is trying to roll back.
    """

    __tablename__ = "resource_versions"
    __table_args__ = (
        UniqueConstraint(
            "resource_type", "resource_id", "version", name="uq_resource_versions_number"
        ),
        # The only hot query: this resource's history, newest first.
        Index("ix_resource_versions_resource", "resource_type", "resource_id", "version"),
        Index("ix_resource_versions_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # A sentence about what changed, generated from the diff against the parent.
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Set when this version was produced by restoring an older one.
    restored_from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChangeRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed edit waiting for someone to look at it."""

    __tablename__ = "change_requests"
    __table_args__ = (
        Index("ix_change_requests_project_status", "project_id", "status"),
        Index("ix_change_requests_resource", "resource_type", "resource_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What the resource looked like when the change was proposed, and what it
    # would become. Keeping both is what lets a reviewer see a diff without
    # re-reading the live resource, which may have moved on since.
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One thing somebody did.

    Written by the gateway for every request that could change something, so
    coverage does not depend on each service remembering to log. That means the
    row describes the *request*, not the domain object -- which is the honest
    unit anyway: it records the attempt, including the ones that were refused.
    """

    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_project_created", "project_id", "created_at"),
        Index("ix_audit_entries_actor", "actor_user_id", "created_at"),
        Index("ix_audit_entries_outcome", "outcome"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A note left on something, and the replies to it."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_target", "target_type", "target_id", "created_at"),
        Index("ix_comments_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Usernames parsed out of the body at write time, so a mention survives the
    # user later being renamed and does not need re-parsing on every read.
    mentions_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
