"""weekly summaries for notification targets

Adoption-readiness A6 (W6): an email or Slack target can subscribe to a weekly
round-up of its project. The ticker sends one when this is NULL or a week old.

Revision ID: 0050_weekly_summaries
Revises: 0049_organisation_networks
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0050_weekly_summaries'
down_revision = '0049_organisation_networks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'external_notification_targets',
        sa.Column('last_summary_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('external_notification_targets', 'last_summary_sent_at')
