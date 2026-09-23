from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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


class DatasetMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measurement of one dataset at one point in time.

    Stored long and narrow rather than one row per profile: metrics get added
    over time, and a wide table would need a migration for each one. The cost
    is more rows, which the composite index below is sized for.
    """

    __tablename__ = "dataset_metrics"
    __table_args__ = (
        # The only query that matters: this metric, this dataset, newest first.
        Index("ix_dataset_metrics_series", "dataset_id", "metric_key", "column_name", "captured_at"),
        Index("ix_dataset_metrics_project_captured", "project_id", "captured_at"),
        Index("ix_dataset_metrics_run", "workflow_run_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    # Which run produced this measurement, when one did.
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )

    metric_key: Mapped[str] = mapped_column(String(48), nullable=False)
    # Null for dataset-wide metrics such as row_count.
    column_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The slot the producing run stood for, so a backfill charts where it belongs.
    logical_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FreshnessPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A promise about how old a dataset is allowed to get."""

    __tablename__ = "freshness_policies"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_freshness_policies_dataset"),
        Index("ix_freshness_policies_project_id", "project_id"),
        Index("ix_freshness_policies_enabled", "project_id", "enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    max_age_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_age_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A problem someone has to deal with, not another line in a log.

    The fingerprint is what stops an incident list from becoming a firehose: a
    rule that fails on twenty consecutive runs is one incident that recurred
    twenty times, not twenty incidents.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_project_status", "project_id", "status"),
        Index("ix_incidents_fingerprint", "project_id", "fingerprint", "status"),
        Index("ix_incidents_dataset_id", "dataset_id"),
        Index("ix_incidents_opened_at", "opened_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class IncidentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One entry on an incident's timeline."""

    __tablename__ = "incident_events"
    __table_args__ = (
        Index("ix_incident_events_incident_id", "incident_id", "sequence"),
        Index("ix_incident_events_project_id", "project_id"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Timestamps cannot order this. `created_at` defaults to now(), which in
    # Postgres is the *transaction* start time, so every event written by one
    # request carries an identical value and the order becomes whatever the
    # tiebreaker happens to be. An explicit counter makes the timeline the
    # order things actually occurred in.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class RuntimeHeartbeat(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ground truth that a background component is alive.

    P0 could only *infer* whether anything was draining the queue: it watched
    for work that sat too long. That is a lagging signal -- it cannot tell a
    healthy idle queue from a dead worker until work piles up. A heartbeat is
    the leading signal: each loop of a worker or ticker writes its own row, so
    "is the worker running right now?" becomes a fact, not a guess.

    One row per (component, host): several replicas of the same component each
    keep their own beat, and a component that has never run simply has no row.
    `interval_seconds` travels with the beat so the reader can judge staleness
    against the loop's own cadence -- a 60s ticker is not late at 30s, but a 5s
    worker is.
    """

    __tablename__ = "runtime_heartbeats"
    __table_args__ = (
        UniqueConstraint("component", "host", name="uq_runtime_heartbeats_component_host"),
        Index("ix_runtime_heartbeats_component", "component"),
    )

    component: Mapped[str] = mapped_column(String(48), nullable=False)
    host: Mapped[str] = mapped_column(String(200), nullable=False)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
