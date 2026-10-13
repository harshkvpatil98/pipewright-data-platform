"""rate limit windows

Adoption-readiness A7 (X5): sign-in, one-time codes, public dashboards and
inbound webhooks are limited per caller, counted here so every gateway shares
one limit.

Revision ID: 0052_rate_limits
Revises: 0051_workflow_retries
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0052_rate_limits'
down_revision = '0051_workflow_retries'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rate_limit_windows',
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('key', 'window_start'),
    )
    op.create_index('ix_rate_limit_windows_window_start', 'rate_limit_windows', ['window_start'])


def downgrade() -> None:
    op.drop_index('ix_rate_limit_windows_window_start', table_name='rate_limit_windows')
    op.drop_table('rate_limit_windows')
