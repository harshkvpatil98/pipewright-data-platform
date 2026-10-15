from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_auth.models import User
    from service_projects.models import Project
    from service_transformations.models import TransformationPipeline


class PipelineRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_project_id", "project_id"),
        Index("ix_pipeline_runs_triggered_by_user_id", "triggered_by_user_id"),
        Index("ix_pipeline_runs_status", "status"),
        Index("ix_pipeline_runs_run_type", "run_type"),
        Index("ix_pipeline_runs_pipeline_id", "pipeline_id"),
        # A project's activity, newest first (A8, Y6).
        Index("ix_pipeline_runs_project_completed", "project_id", "completed_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    triggered_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformation_pipelines.id", ondelete="SET NULL"), nullable=True
    )
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    logs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # A run the worker does instead of the request (A7, X3): what to do, and
    # the lease of the worker doing it.
    request_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    claim_owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Who started it (D2, O8): a person, a schedule, a backfill, or a workflow
    #: run it is part of. Decides what the worker takes first and what counts
    #: towards the project's runs at once (`service_pipeline_runs.limits`).
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="person", server_default="person")

    project: Mapped[Project] = relationship(back_populates="pipeline_runs")
    triggered_by_user: Mapped[User] = relationship(back_populates="pipeline_runs")
    transformation_pipeline: Mapped["TransformationPipeline | None"] = relationship(
        "TransformationPipeline",
        foreign_keys=[pipeline_id],
        back_populates="pipeline_runs",
    )
