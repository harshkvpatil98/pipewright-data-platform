"""scheduled operations

Revision ID: 0009_scheduled_operations
Revises: 0008_destination_configs
Create Date: 2026-04-09 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_scheduled_operations"
down_revision: str | None = "0008_destination_configs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schedule_type", sa.String(length=64), nullable=False),
        sa.Column("cron_expression", sa.String(length=512), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("target_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_operations_project_id", "scheduled_operations", ["project_id"], unique=False)
    op.create_index("ix_scheduled_operations_schedule_type", "scheduled_operations", ["schedule_type"], unique=False)
    op.create_index("ix_scheduled_operations_enabled", "scheduled_operations", ["enabled"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scheduled_operations_enabled", table_name="scheduled_operations")
    op.drop_index("ix_scheduled_operations_schedule_type", table_name="scheduled_operations")
    op.drop_index("ix_scheduled_operations_project_id", table_name="scheduled_operations")
    op.drop_table("scheduled_operations")
