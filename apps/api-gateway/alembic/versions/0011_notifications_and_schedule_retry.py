"""notifications and schedule retry metadata

Revision ID: 0011_notifications_and_schedule_retry
Revises: 0010_schedule_runtime_metadata
Create Date: 2026-04-07 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_notifications_and_schedule_retry"
down_revision: str | None = "0010_schedule_runtime_metadata"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_operations",
        sa.Column("retry_count_current", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_operations_enabled_next_retry",
        "scheduled_operations",
        ["enabled", "next_retry_at"],
        unique=False,
    )
    op.alter_column("scheduled_operations", "retry_count_current", server_default=None)
    op.alter_column("scheduled_operations", "max_retries", server_default=None)

    op.create_table(
        "user_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("related_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_pipeline_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_pipeline_id"], ["transformation_pipelines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_schedule_id"], ["scheduled_operations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"], unique=False)
    op.create_index(
        "ix_user_notifications_user_created",
        "user_notifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_notifications_user_unread",
        "user_notifications",
        ["user_id", "is_read"],
        unique=False,
    )
    op.alter_column("user_notifications", "is_read", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_user_notifications_user_unread", table_name="user_notifications")
    op.drop_index("ix_user_notifications_user_created", table_name="user_notifications")
    op.drop_index("ix_user_notifications_user_id", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_index("ix_scheduled_operations_enabled_next_retry", table_name="scheduled_operations")
    op.drop_column("scheduled_operations", "last_failure_at")
    op.drop_column("scheduled_operations", "next_retry_at")
    op.drop_column("scheduled_operations", "max_retries")
    op.drop_column("scheduled_operations", "retry_count_current")
