"""every event sent to a webhook, with each attempt's outcome

Adoption-readiness A8 (Y1): signed webhooks are tried up to three times and
each attempt is shown on the target, so a partner can see what was sent and
why it did or did not arrive.

Revision ID: 0056_webhook_deliveries
Revises: 0055_version_ingest_spec
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0056_webhook_deliveries'
down_revision = '0055_version_ingest_spec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['target_id'], ['external_notification_targets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhook_deliveries_target_created', 'webhook_deliveries', ['target_id', 'created_at'])
    op.create_index('ix_webhook_deliveries_due', 'webhook_deliveries', ['status', 'next_attempt_at'])


def downgrade() -> None:
    op.drop_index('ix_webhook_deliveries_due', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_target_created', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
