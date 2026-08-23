"""version history, approvals, audit log, and comments

Four tables that together answer "who changed what, when, and can we put it
back". Snapshots are stored whole rather than as deltas: reconstructing a
version from a chain of deltas breaks at the exact moment somebody is trying to
roll back, which is the worst possible time.

Revision ID: 0022_governance
Revises: 0021_project_memberships
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022_governance'
down_revision = '0021_project_memberships'
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "resource_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("restored_from_version", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("resource_type", "resource_id", "version", name="uq_resource_versions_number"),
    )
    op.create_index("ix_resource_versions_resource", "resource_versions", ["resource_type", "resource_id", "version"])
    op.create_index("ix_resource_versions_project_id", "resource_versions", ["project_id"])

    op.create_table(
        "change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_change_requests_project_status", "change_requests", ["project_id", "status"])
    op.create_index("ix_change_requests_resource", "change_requests", ["resource_type", "resource_id"])

    op.create_table(
        "audit_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_audit_entries_project_created", "audit_entries", ["project_id", "created_at"])
    op.create_index("ix_audit_entries_actor", "audit_entries", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_entries_outcome", "audit_entries", ["outcome"])

    op.create_table(
        "comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mentions_json", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_comments_target", "comments", ["target_type", "target_id", "created_at"])
    op.create_index("ix_comments_project_id", "comments", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_project_id", table_name="comments")
    op.drop_index("ix_comments_target", table_name="comments")
    op.drop_table("comments")

    op.drop_index("ix_audit_entries_outcome", table_name="audit_entries")
    op.drop_index("ix_audit_entries_actor", table_name="audit_entries")
    op.drop_index("ix_audit_entries_project_created", table_name="audit_entries")
    op.drop_table("audit_entries")

    op.drop_index("ix_change_requests_resource", table_name="change_requests")
    op.drop_index("ix_change_requests_project_status", table_name="change_requests")
    op.drop_table("change_requests")

    op.drop_index("ix_resource_versions_project_id", table_name="resource_versions")
    op.drop_index("ix_resource_versions_resource", table_name="resource_versions")
    op.drop_table("resource_versions")
