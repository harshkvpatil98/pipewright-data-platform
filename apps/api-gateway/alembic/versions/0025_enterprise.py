"""organisations, fine-grained security, retention, erasure, and usage

The tenancy columns on `users` and `projects` are nullable on purpose. A
single-tenant installation upgrades with no data migration: an unassigned user
matches an unassigned project, so nothing changes until somebody creates an
organisation.

Retention policies default to report-only. A policy that starts deleting the
moment it is saved is a policy nobody dares create.

Revision ID: 0025_enterprise
Revises: 0024_reporting_and_catalog
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025_enterprise'
down_revision = '0024_reporting_and_catalog'
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="standard"),
        sa.Column("max_projects", sa.Integer(), nullable=True),
        sa.Column("max_datasets", sa.Integer(), nullable=True),
        sa.Column("max_rows_per_month", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_organisations_slug"),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"])

    op.add_column("users", sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("projects", sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_users_organisation_id", "users", ["organisation_id"])
    op.create_index("ix_projects_organisation_id", "projects", ["organisation_id"])

    op.create_table(
        "security_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("row_rules_json", sa.JSON(), nullable=True),
        sa.Column("column_rules_json", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_security_policies_dataset", "security_policies", ["dataset_id", "enabled"])
    op.create_index("ix_security_policies_project_id", "security_policies", ["project_id"])

    op.create_table(
        "retention_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("retain_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_deleted_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "resource_type", name="uq_retention_project_resource"),
    )
    op.create_index("ix_retention_policies_project_id", "retention_policies", ["project_id"])

    op.create_table(
        "erasure_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_value", sa.String(length=320), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False, server_default="email"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("datasets_searched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_affected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_erasure_requests_project_status", "erasure_requests", ["project_id", "status"])

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_name", sa.String(length=200), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compute_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("bytes_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_usage_records_project_period", "usage_records", ["project_id", "recorded_at"])
    op.create_index("ix_usage_records_org_period", "usage_records", ["organisation_id", "recorded_at"])
    op.create_index("ix_usage_records_subject", "usage_records", ["subject_type", "subject_id"])


def downgrade() -> None:
    for index, table in (
        ("ix_usage_records_subject", "usage_records"),
        ("ix_usage_records_org_period", "usage_records"),
        ("ix_usage_records_project_period", "usage_records"),
        ("ix_erasure_requests_project_status", "erasure_requests"),
        ("ix_retention_policies_project_id", "retention_policies"),
        ("ix_security_policies_project_id", "security_policies"),
        ("ix_security_policies_dataset", "security_policies"),
    ):
        op.drop_index(index, table_name=table)

    for table in ("usage_records", "erasure_requests", "retention_policies", "security_policies"):
        op.drop_table(table)

    op.drop_index("ix_projects_organisation_id", table_name="projects")
    op.drop_index("ix_users_organisation_id", table_name="users")
    op.drop_column("projects", "organisation_id")
    op.drop_column("users", "organisation_id")

    op.drop_index("ix_organisations_slug", table_name="organisations")
    op.drop_table("organisations")
