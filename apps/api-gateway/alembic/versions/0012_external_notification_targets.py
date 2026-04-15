"""external notification targets (email + slack webhook)

Revision ID: 0012_external_notification_targets
Revises: 0011_notifications_and_schedule_retry
Create Date: 2026-04-11 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_external_notification_targets"
down_revision: str | None = "0011_notifications_and_schedule_retry"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_notification_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("subscribed_event_types_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_notification_targets_project_id",
        "external_notification_targets",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_notification_targets_target_type",
        "external_notification_targets",
        ["target_type"],
        unique=False,
    )
    op.create_index(
        "ix_external_notification_targets_enabled",
        "external_notification_targets",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        "ix_external_notification_targets_project_enabled",
        "external_notification_targets",
        ["project_id", "enabled"],
        unique=False,
    )
    op.alter_column("external_notification_targets", "enabled", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_external_notification_targets_project_enabled", table_name="external_notification_targets")
    op.drop_index("ix_external_notification_targets_enabled", table_name="external_notification_targets")
    op.drop_index("ix_external_notification_targets_target_type", table_name="external_notification_targets")
    op.drop_index("ix_external_notification_targets_project_id", table_name="external_notification_targets")
    op.drop_table("external_notification_targets")
