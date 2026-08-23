"""charts, dashboards, scheduled reports, the catalog, and the glossary

The phase where somebody who will never open a pipeline editor gets something
out of the platform. The chore being removed is a person exporting the same
spreadsheet every Monday and emailing it round.

A chart's whole query is stored as one document rather than in columns: a chart
is only meaningful as a complete question, and splitting it across columns would
make half-saved states representable.

Revision ID: 0024_reporting_and_catalog
Revises: 0023_project_environments
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024_reporting_and_catalog'
down_revision = '0023_project_environments'
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "saved_charts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("chart_type", sa.String(length=24), nullable=False, server_default="bar"),
        sa.Column("query_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_saved_charts_project_id", "saved_charts", ["project_id"])
    op.create_index("ix_saved_charts_dataset_id", "saved_charts", ["dataset_id"])

    op.create_table(
        "dashboards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("share_token", sa.String(length=64), nullable=True),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("share_token", name="uq_dashboards_share_token"),
    )
    op.create_index("ix_dashboards_project_id", "dashboards", ["project_id"])

    op.create_table(
        "dashboard_tiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dashboard_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chart_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("saved_charts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_dashboard_tiles_dashboard_id", "dashboard_tiles", ["dashboard_id", "position"])

    op.create_table(
        "scheduled_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False, server_default="dataset"),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False, server_default="excel"),
        sa.Column("cron_expression", sa.String(length=120), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipients_json", sa.JSON(), nullable=True),
        sa.Column("notification_target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_scheduled_reports_project_id", "scheduled_reports", ["project_id"])
    op.create_index("ix_scheduled_reports_next_run", "scheduled_reports", ["enabled", "next_run_at"])

    op.create_table(
        "report_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scheduled_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="succeeded"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("generated_ms", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_report_deliveries_report", "report_deliveries", ["report_id", "created_at"])

    op.create_table(
        "glossary_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bindings_json", sa.JSON(), nullable=True),
        sa.Column("synonyms_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "slug", name="uq_glossary_terms_project_slug"),
    )
    op.create_index("ix_glossary_terms_project_id", "glossary_terms", ["project_id"])

    op.create_table(
        "catalog_annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("certified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certified_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("column_notes_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("dataset_id", name="uq_catalog_annotations_dataset"),
    )
    op.create_index("ix_catalog_annotations_project_id", "catalog_annotations", ["project_id"])
    op.create_index("ix_catalog_annotations_certified", "catalog_annotations", ["project_id", "certified"])


def downgrade() -> None:
    for index, table in (
        ("ix_catalog_annotations_certified", "catalog_annotations"),
        ("ix_catalog_annotations_project_id", "catalog_annotations"),
        ("ix_glossary_terms_project_id", "glossary_terms"),
        ("ix_report_deliveries_report", "report_deliveries"),
        ("ix_scheduled_reports_next_run", "scheduled_reports"),
        ("ix_scheduled_reports_project_id", "scheduled_reports"),
        ("ix_dashboard_tiles_dashboard_id", "dashboard_tiles"),
        ("ix_dashboards_project_id", "dashboards"),
        ("ix_saved_charts_dataset_id", "saved_charts"),
        ("ix_saved_charts_project_id", "saved_charts"),
    ):
        op.drop_index(index, table_name=table)

    for table in (
        "catalog_annotations",
        "glossary_terms",
        "report_deliveries",
        "scheduled_reports",
        "dashboard_tiles",
        "dashboards",
        "saved_charts",
    ):
        op.drop_table(table)
