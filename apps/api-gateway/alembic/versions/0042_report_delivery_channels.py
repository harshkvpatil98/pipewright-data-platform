"""report_deliveries.channels_json: where a report actually went

A delivery recorded that a file was generated; it did not record whether the
Slack post or the emails that were supposed to carry it succeeded. Each
delivery now keeps a per-channel outcome list (in-app, Slack target, email
target, each recipient) so "delivered" is a fact per channel, not a hope.
Schema only.

Revision ID: 0042_report_delivery_channels
Revises: 0041_dashboard_builder_v2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0042_report_delivery_channels'
down_revision = '0041_dashboard_builder_v2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('report_deliveries', sa.Column('channels_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('report_deliveries', 'channels_json')
