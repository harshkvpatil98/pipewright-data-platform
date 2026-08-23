"""add logical_date to workflow runs

The slot a run represents, as distinct from when it executed. Date macros in
node configuration resolve against this, which is what lets a backfill for last
March produce March's values rather than today's.

Nullable because a manual run has no slot of its own and stands for the present.

Revision ID: 0019_workflow_run_logical_date
Revises: 0018_notification_timestamp_defaults
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0019_workflow_run_logical_date'
down_revision = '0018_notification_timestamp_defaults'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("logical_date", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfills and run history are browsed by slot, so index it.
    op.create_index(
        "ix_workflow_runs_workflow_logical",
        "workflow_runs",
        ["workflow_id", "logical_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow_logical", table_name="workflow_runs")
    op.drop_column("workflow_runs", "logical_date")
