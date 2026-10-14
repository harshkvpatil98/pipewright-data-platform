"""alerts on a dataset's measures, and each time one crossed or came back

Adoption-readiness A8 (Y5): a line a measure should not cross (above, below,
or a change of more than a share since the last time), checked whenever the
dataset gets new data, and sent to the project's people and alert targets.

Revision ID: 0058_metric_alerts
Revises: 0057_dashboard_embeds
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0058_metric_alerts'
down_revision = '0057_dashboard_embeds'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'metric_alerts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('metric_key', sa.String(length=48), nullable=False),
        sa.Column('column_name', sa.String(length=128), nullable=True),
        sa.Column('condition', sa.String(length=16), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('state', sa.String(length=16), server_default='ok', nullable=False),
        sa.Column('last_value', sa.Float(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_metric_alerts_dataset', 'metric_alerts', ['dataset_id'])
    op.create_table(
        'metric_alert_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('alert_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('previous_value', sa.Float(), nullable=True),
        sa.Column('title', sa.String(length=240), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['alert_id'], ['metric_alerts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_metric_alert_events_project_created', 'metric_alert_events', ['project_id', 'created_at'])
    op.create_index('ix_metric_alert_events_unsent', 'metric_alert_events', ['sent_at'])


def downgrade() -> None:
    op.drop_index('ix_metric_alert_events_unsent', table_name='metric_alert_events')
    op.drop_index('ix_metric_alert_events_project_created', table_name='metric_alert_events')
    op.drop_table('metric_alert_events')
    op.drop_index('ix_metric_alerts_dataset', table_name='metric_alerts')
    op.drop_table('metric_alerts')
