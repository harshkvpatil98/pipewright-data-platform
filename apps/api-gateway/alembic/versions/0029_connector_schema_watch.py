"""Connector schema watch: the last schema seen per connection stream

One row per (project, connection, stream), holding the *current* answer rather
than a history. The history of what changed is the incident timeline, which is
where somebody looking at a drift already is; a second copy here would be a
worse one that nothing reads.

Revision ID: 0029_connector_schema_watch
Revises: 0028_workbench
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0029_connector_schema_watch'
down_revision = '0028_workbench'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'connector_schema_snapshots',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connection_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('connector_type', sa.String(length=64), nullable=False),
        sa.Column('stream_name', sa.String(length=200), nullable=False),
        sa.Column('columns_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='declared'),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_severity', sa.String(length=16), nullable=False, server_default='none'),
        sa.Column('last_summary', sa.Text(), nullable=True),
        sa.Column('drift_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index(
        'ix_connector_schema_snapshots_project_id',
        'connector_schema_snapshots',
        ['project_id'],
    )
    # Unique, so two sweeps racing cannot leave two disagreeing "last seen"
    # answers for the same stream.
    op.create_index(
        'ix_connector_schema_snapshots_identity',
        'connector_schema_snapshots',
        ['project_id', 'connection_id', 'stream_name'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_connector_schema_snapshots_identity', table_name='connector_schema_snapshots')
    op.drop_index('ix_connector_schema_snapshots_project_id', table_name='connector_schema_snapshots')
    op.drop_table('connector_schema_snapshots')
