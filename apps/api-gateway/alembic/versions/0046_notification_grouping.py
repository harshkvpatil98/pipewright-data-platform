"""notification grouping and per-person preferences

Adoption-readiness A2: notifications stopped being a firehose. A repeat of the
same failure for the same object folds into one row with a count
(`group_key`, `group_count`), routine successes become one running summary a
day, and each person chooses per category whether they hear about each event,
a daily summary, or nothing (`notification_preferences`). Schema only; rows
written before this read as a group of one.

Revision ID: 0046_notification_grouping
Revises: 0045_stream_sources
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0046_notification_grouping'
down_revision = '0045_stream_sources'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_notifications', sa.Column('group_key', sa.String(length=200), nullable=True))
    op.add_column(
        'user_notifications',
        sa.Column('group_count', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index(
        'ix_user_notifications_user_group', 'user_notifications', ['user_id', 'group_key']
    )
    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'category', name='uq_notification_preferences_user_category'),
    )


def downgrade() -> None:
    op.drop_table('notification_preferences')
    op.drop_index('ix_user_notifications_user_group', table_name='user_notifications')
    op.drop_column('user_notifications', 'group_count')
    op.drop_column('user_notifications', 'group_key')
