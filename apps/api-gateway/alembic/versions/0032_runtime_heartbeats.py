"""Runtime heartbeats: ground truth that a background worker is alive

P0 could only infer runtime health from work that sat too long -- a lagging
signal that cannot tell a healthy idle queue from a dead worker. Each loop of a
worker or ticker now writes its own beat here, so "is the worker running right
now?" is a fact. One row per (component, host); a component that has never run
simply has no row.

Revision ID: 0032_runtime_heartbeats
Revises: 0031_identity_core
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0032_runtime_heartbeats'
down_revision = '0031_identity_core'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'runtime_heartbeats',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('component', sa.String(length=48), nullable=False),
        sa.Column('host', sa.String(length=200), nullable=False),
        sa.Column('beat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('interval_seconds', sa.Float(), nullable=False, server_default='5'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='running'),
        sa.Column('detail_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('component', 'host', name='uq_runtime_heartbeats_component_host'),
    )
    op.create_index('ix_runtime_heartbeats_component', 'runtime_heartbeats', ['component'])


def downgrade() -> None:
    op.drop_index('ix_runtime_heartbeats_component', table_name='runtime_heartbeats')
    op.drop_table('runtime_heartbeats')
