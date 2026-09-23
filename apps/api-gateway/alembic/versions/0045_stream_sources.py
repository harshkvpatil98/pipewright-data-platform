"""stream_sources and stream_events: inbound webhooks and Postgres CDC

Phase 20, the honest first slice: a source that receives rows instead of
being polled for them. A webhook source is an endpoint (token-authenticated,
hash at rest) whose events are stored as they arrive; a postgres_cdc source
follows a database's own change log through a logical replication slot,
micro-batch, at-least-once. Both materialise into an append-only, versioned
dataset. Schema only.

Revision ID: 0045_stream_sources
Revises: 0044_metrics
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0045_stream_sources'
down_revision = '0044_metrics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stream_sources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='active'),
        sa.Column('connection_id', sa.Uuid(), nullable=True),
        sa.Column('config_json', sa.JSON(), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=True),
        sa.Column('cursor', sa.Text(), nullable=True),
        sa.Column('dataset_id', sa.Uuid(), nullable=True),
        sa.Column('events_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_materialised_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['extraction_connections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_stream_sources_token_hash'),
    )
    op.create_index('ix_stream_sources_project_id', 'stream_sources', ['project_id'])
    op.create_table(
        'stream_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('table_name', sa.String(length=320), nullable=True),
        sa.Column('position', sa.String(length=64), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['stream_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'seq', name='uq_stream_events_source_seq'),
    )
    op.create_index('ix_stream_events_source_id', 'stream_events', ['source_id', 'seq'])
    op.create_index('ix_stream_events_position', 'stream_events', ['source_id', 'position'])


def downgrade() -> None:
    op.drop_index('ix_stream_events_position', table_name='stream_events')
    op.drop_index('ix_stream_events_source_id', table_name='stream_events')
    op.drop_table('stream_events')
    op.drop_index('ix_stream_sources_project_id', table_name='stream_sources')
    op.drop_table('stream_sources')
