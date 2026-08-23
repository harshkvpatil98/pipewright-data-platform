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
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SavedChart(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A question about a dataset, saved so it can be asked again."""

    __tablename__ = "saved_charts"
    __table_args__ = (
        Index("ix_saved_charts_project_id", "project_id"),
        Index("ix_saved_charts_dataset_id", "dataset_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_type: Mapped[str] = mapped_column(String(24), nullable=False, default="bar")
    # The whole query -- dimensions, measures, filters, sort -- as one document.
    # Stored together because a chart is only meaningful as a complete question.
    query_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    options_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Dashboard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A page of charts."""

    __tablename__ = "dashboards"
    __table_args__ = (
        Index("ix_dashboards_project_id", "project_id"),
        UniqueConstraint("share_token", name="uq_dashboards_share_token"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Filters applied to every tile, so a dashboard can be scoped in one place
    # rather than editing each chart.
    filters_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # Null until somebody shares it. Presence of a token is what makes a
    # dashboard readable without signing in, so it is granted, never default.
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DashboardTile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One chart's place on a dashboard."""

    __tablename__ = "dashboard_tiles"
    __table_args__ = (Index("ix_dashboard_tiles_dashboard_id", "dashboard_id", "position"),)

    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False
    )
    chart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_charts.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ScheduledReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file, generated from live data and delivered on a schedule.

    The chore this removes: somebody exporting the same spreadsheet every Monday
    and emailing it round.
    """

    __tablename__ = "scheduled_reports"
    __table_args__ = (
        Index("ix_scheduled_reports_project_id", "project_id"),
        Index("ix_scheduled_reports_next_run", "enabled", "next_run_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What to put in it: a dashboard, a chart, or a dataset straight out.
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="dataset")
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False, default="excel")

    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Where it goes. Notification targets are reused so Slack and email
    # delivery do not get a second implementation.
    recipients_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    notification_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReportDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One generated report, kept so it can be downloaded again."""

    __tablename__ = "report_deliveries"
    __table_args__ = (Index("ix_report_deliveries_report", "report_id", "created_at"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_reports.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class GlossaryTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a word means here, bound to the columns that hold it.

    The point is not the definition, it is the binding: 'revenue' meaning one
    thing is only enforceable if the term knows which columns it covers.
    """

    __tablename__ = "glossary_terms"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_glossary_terms_project_slug"),
        Index("ix_glossary_terms_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # [{"dataset_id": ..., "column": ...}] -- which columns this term covers.
    bindings_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    synonyms_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class CatalogAnnotation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What people added to a dataset that the data itself does not say."""

    __tablename__ = "catalog_annotations"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_catalog_annotations_dataset"),
        Index("ix_catalog_annotations_project_id", "project_id"),
        Index("ix_catalog_annotations_certified", "project_id", "certified"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # A certified dataset is one somebody put their name against.
    certified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    certified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # {"column_name": "what it means"} -- descriptions the schema cannot hold.
    column_notes_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
