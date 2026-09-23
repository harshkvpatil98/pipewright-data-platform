"""dataset_versions: an immutable snapshot per materialisation

The storage foundation for time travel (Phase 18). Each successful dataset
materialisation appends one row here; version_number is 1-based and monotonic per
dataset, and (dataset_id, version_number) is unique so a concurrent double
publish cannot mint the same number twice. This migration creates the table only
(settled decision #5: a migration performs schema changes, never a data
backfill); datasets materialised before it carry no recorded history until their
next materialisation.

Revision ID: 0038_dataset_versions
Revises: 0037_erasure_mode
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0038_dataset_versions'
down_revision = '0037_erasure_mode'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dataset_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=80), nullable=True),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_type', sa.String(length=16), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('column_count', sa.Integer(), nullable=True),
        sa.Column('schema_json', sa.JSON(), nullable=True),
        sa.Column('pipeline_run_id', sa.Uuid(), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', 'version_number', name='uq_dataset_versions_dataset_number'),
    )
    op.create_index('ix_dataset_versions_dataset_id', 'dataset_versions', ['dataset_id'])
    op.create_index('ix_dataset_versions_content_hash', 'dataset_versions', ['content_hash'])


def downgrade() -> None:
    op.drop_index('ix_dataset_versions_content_hash', table_name='dataset_versions')
    op.drop_index('ix_dataset_versions_dataset_id', table_name='dataset_versions')
    op.drop_table('dataset_versions')
