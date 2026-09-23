"""Durable upload sessions: a chunked upload survives a gateway restart

The chunks of a large upload were always written to storage as they arrived,
but the record of which chunks had landed lived in process memory -- so a
restart orphaned a half-finished upload, leaving parts on disk with nothing
that knew how to reassemble them. This table holds that record, so a resume
survives a restart and any gateway process can serve any upload.

Revision ID: 0033_upload_sessions
Revises: 0032_runtime_heartbeats
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0033_upload_sessions'
down_revision = '0032_runtime_heartbeats'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'upload_sessions',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('total_bytes', sa.BigInteger(), nullable=False),
        sa.Column('chunk_bytes', sa.BigInteger(), nullable=False),
        sa.Column('expected_sha256', sa.String(length=64), nullable=True),
        sa.Column('received_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_by_user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_upload_sessions_project_id', 'upload_sessions', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_upload_sessions_project_id', table_name='upload_sessions')
    op.drop_table('upload_sessions')
