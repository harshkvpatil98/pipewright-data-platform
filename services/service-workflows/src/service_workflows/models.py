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


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A directed graph of work: extract, transform, validate, publish, notify."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_project_id", "project_id"),
        Index("ix_workflows_project_enabled", "project_id", "enabled"),
        Index("ix_workflows_next_run_at", "next_run_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Defaults merged into every run's parameters; a run may override them.
    default_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkflowNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One unit of work inside a workflow."""

    __tablename__ = "workflow_nodes"
    __table_args__ = (
        # Node keys are referenced by other nodes' config, so they must be unique
        # within their workflow.
        UniqueConstraint("workflow_id", "node_key", name="uq_workflow_nodes_workflow_key"),
        Index("ix_workflow_nodes_workflow_id", "workflow_id"),
        Index("ix_workflow_nodes_project_id", "project_id"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # A failure here is recorded but does not fail the whole run.
    continue_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Canvas coordinates, stored now so the visual editor has somewhere to write.
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class WorkflowEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A dependency between two nodes, followed only when its condition holds."""

    __tablename__ = "workflow_edges"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "from_node_key", "to_node_key", name="uq_workflow_edges_pair"
        ),
        Index("ix_workflow_edges_workflow_id", "workflow_id"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    from_node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    to_node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    condition: Mapped[str] = mapped_column(String(24), nullable=False, default="on_success")


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a whole workflow, and the queue row a worker claims."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        Index("ix_workflow_runs_project_created", "project_id", "created_at"),
        # The claim query filters on status and orders by queued_at.
        Index("ix_workflow_runs_status_queued", "status", "queued_at"),
        Index("ix_workflow_runs_workflow_logical", "workflow_id", "logical_date"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    # The slot this run represents, which date macros resolve against. A cron
    # run carries its scheduled instant; a backfill run carries its slot.
    logical_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parameters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Lease fields: a worker claims a queued run and must refresh or lose it.
    claim_owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    nodes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkflowNodeRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The outcome of one node within one workflow run."""

    __tablename__ = "workflow_node_runs"
    __table_args__ = (
        Index("ix_workflow_node_runs_run_id", "workflow_run_id"),
        Index("ix_workflow_node_runs_project_id", "project_id"),
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Kept as a key rather than a foreign key so a node run survives its node
    # being edited or deleted; run history must stay readable.
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str] = mapped_column(String(160), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # What the node produced, e.g. {"dataset_id": ..., "row_count": ...}. Later
    # nodes read this to resolve `dataset_from`.
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Links to the existing run record when a node delegated to one.
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
