"""schedule runtime metadata

Revision ID: 0010_schedule_runtime_metadata
Revises: 0009_scheduled_operations
Create Date: 2026-04-10 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_schedule_runtime_metadata"
down_revision: str | None = "0009_scheduled_operations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_operations",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("last_run_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("last_run_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("last_run_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("last_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_scheduled_operations_enabled_next_run",
        "scheduled_operations",
        ["enabled", "next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_operations_enabled_next_run", table_name="scheduled_operations")
    op.drop_column("scheduled_operations", "execution_count")
    op.drop_column("scheduled_operations", "last_error_message")
    op.drop_column("scheduled_operations", "last_run_status")
    op.drop_column("scheduled_operations", "last_run_finished_at")
    op.drop_column("scheduled_operations", "last_run_started_at")
    op.drop_column("scheduled_operations", "next_run_at")
