"""metric history, freshness policies, and incidents

Phase 02 turns "did the run succeed" into "did it produce the right numbers".
That needs three things stored:

* ``dataset_metrics`` -- long and narrow, so a new metric never needs a
  migration. The composite index matches the only hot query: one metric, one
  dataset, newest first.
* ``freshness_policies`` -- one per dataset, enforced by a unique constraint so
  two contradictory promises cannot exist.
* ``incidents`` and ``incident_events`` -- grouped by fingerprint so a nightly
  failure is one incident that recurred, not thirty separate alerts.

Revision ID: 0020_observability_metrics_and_incidents
Revises: 0019_workflow_run_logical_date
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020_observability_metrics_and_incidents'
down_revision = '0019_workflow_run_logical_date'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metric_key", sa.String(length=48), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("logical_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_dataset_metrics_series",
        "dataset_metrics",
        ["dataset_id", "metric_key", "column_name", "captured_at"],
    )
    op.create_index("ix_dataset_metrics_project_captured", "dataset_metrics", ["project_id", "captured_at"])
    op.create_index("ix_dataset_metrics_run", "dataset_metrics", ["workflow_run_id"])

    op.create_table(
        "freshness_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("max_age_minutes", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="high"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_age_minutes", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("dataset_id", name="uq_freshness_policies_dataset"),
    )
    op.create_index("ix_freshness_policies_project_id", "freshness_policies", ["project_id"])
    op.create_index("ix_freshness_policies_enabled", "freshness_policies", ["project_id", "enabled"])

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="high"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_incidents_project_status", "incidents", ["project_id", "status"])
    op.create_index("ix_incidents_fingerprint", "incidents", ["project_id", "fingerprint", "status"])
    op.create_index("ix_incidents_dataset_id", "incidents", ["dataset_id"])
    op.create_index("ix_incidents_opened_at", "incidents", ["opened_at"])

    op.create_table(
        "incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id", "sequence"])
    op.create_index("ix_incident_events_project_id", "incident_events", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_events_project_id", table_name="incident_events")
    op.drop_index("ix_incident_events_incident_id", table_name="incident_events")
    op.drop_table("incident_events")

    op.drop_index("ix_incidents_opened_at", table_name="incidents")
    op.drop_index("ix_incidents_dataset_id", table_name="incidents")
    op.drop_index("ix_incidents_fingerprint", table_name="incidents")
    op.drop_index("ix_incidents_project_status", table_name="incidents")
    op.drop_table("incidents")

    op.drop_index("ix_freshness_policies_enabled", table_name="freshness_policies")
    op.drop_index("ix_freshness_policies_project_id", table_name="freshness_policies")
    op.drop_table("freshness_policies")

    op.drop_index("ix_dataset_metrics_run", table_name="dataset_metrics")
    op.drop_index("ix_dataset_metrics_project_captured", table_name="dataset_metrics")
    op.drop_index("ix_dataset_metrics_series", table_name="dataset_metrics")
    op.drop_table("dataset_metrics")
