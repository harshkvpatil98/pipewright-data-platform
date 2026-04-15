"""schedule execution claim lease (multi-instance scheduler safety)

Revision ID: 0013_schedule_execution_claim_lease
Revises: 0012_external_notification_targets
Create Date: 2026-04-11 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_schedule_execution_claim_lease"
down_revision: str | None = "0012_external_notification_targets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_operations",
        sa.Column("claim_owner_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("claim_acquired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_operations",
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_operations_claim_expires_at",
        "scheduled_operations",
        ["claim_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_operations_claim_expires_at", table_name="scheduled_operations")
    op.drop_column("scheduled_operations", "claim_expires_at")
    op.drop_column("scheduled_operations", "claim_acquired_at")
    op.drop_column("scheduled_operations", "claim_owner_id")
