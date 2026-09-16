"""Ingest specs: how a recurring kind of file is read

Stored rather than re-inferred. Inference depends on the data, so the same
monthly report can be read two different ways in two consecutive months -- a
column that read as day-first in January because one row said `15/01` is
ambiguous in February when no row does. A recorded decision does not drift.

Revision ID: 0030_ingest_specs
Revises: 0029_connector_schema_watch
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0030_ingest_specs'
down_revision = '0029_connector_schema_watch'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ingest_specs',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('name_pattern', sa.String(length=300), nullable=False),
        sa.Column('column_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('file_format', sa.String(length=32), nullable=False),
        sa.Column('spec_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_ingest_specs_project_id', 'ingest_specs', ['project_id'])
    # The two lookups the upload path makes: the column fingerprint is the
    # reliable key, the name pattern catches a renamed or widened file.
    op.create_index('ix_ingest_specs_fingerprint', 'ingest_specs', ['project_id', 'column_fingerprint'])
    op.create_index('ix_ingest_specs_pattern', 'ingest_specs', ['project_id', 'name_pattern'])

    # The spec a dataset was actually read with, for the audit trail. Nullable
    # because every dataset ingested before this migration has none, and
    # inventing one would be a claim about how they were read.
    op.add_column('datasets', sa.Column('ingest_spec_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('datasets', 'ingest_spec_json')
    op.drop_index('ix_ingest_specs_pattern', table_name='ingest_specs')
    op.drop_index('ix_ingest_specs_fingerprint', table_name='ingest_specs')
    op.drop_index('ix_ingest_specs_project_id', table_name='ingest_specs')
    op.drop_table('ingest_specs')
