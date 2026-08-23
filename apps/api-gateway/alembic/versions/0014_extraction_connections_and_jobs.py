"""extraction connections and jobs

Adds saved database connections and repeatable extraction jobs (including
incremental watermark state).

Note: autogenerate also reports JSONB->JSON and a users.username unique
constraint. Those are pre-existing differences between the models and the
deployed schema, unrelated to this change, so they are deliberately excluded.

Revision ID: 0014_extraction_connections_and_jobs
Revises: 0013_schedule_execution_claim_lease
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0014_extraction_connections_and_jobs'
down_revision = '0013_schedule_execution_claim_lease'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('extraction_connections',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('connector_type', sa.String(length=32), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_test_status', sa.String(length=32), nullable=True),
    sa.Column('last_test_message', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_extraction_connections_connector_type', 'extraction_connections', ['connector_type'], unique=False)
    op.create_index('ix_extraction_connections_project_id', 'extraction_connections', ['project_id'], unique=False)
    op.create_table('extraction_jobs',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_kind', sa.String(length=16), nullable=False),
    sa.Column('source_schema', sa.String(length=160), nullable=True),
    sa.Column('source_table', sa.String(length=320), nullable=True),
    sa.Column('query_sql', sa.Text(), nullable=True),
    sa.Column('load_mode', sa.String(length=32), nullable=False),
    sa.Column('cursor_column', sa.String(length=160), nullable=True),
    sa.Column('primary_key_columns', sa.JSON(), nullable=True),
    sa.Column('max_rows', sa.Integer(), nullable=False),
    sa.Column('watermark_value', sa.Text(), nullable=True),
    sa.Column('watermark_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('target_dataset_id', sa.UUID(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_status', sa.String(length=32), nullable=True),
    sa.Column('last_row_count', sa.Integer(), nullable=True),
    sa.Column('last_error_message', sa.Text(), nullable=True),
    sa.Column('execution_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['extraction_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_extraction_jobs_connection_id', 'extraction_jobs', ['connection_id'], unique=False)
    op.create_index('ix_extraction_jobs_project_enabled', 'extraction_jobs', ['project_id', 'enabled'], unique=False)
    op.create_index('ix_extraction_jobs_project_id', 'extraction_jobs', ['project_id'], unique=False)
    op.create_index('ix_extraction_jobs_target_dataset_id', 'extraction_jobs', ['target_dataset_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_extraction_jobs_target_dataset_id', table_name='extraction_jobs')
    op.drop_index('ix_extraction_jobs_project_id', table_name='extraction_jobs')
    op.drop_index('ix_extraction_jobs_project_enabled', table_name='extraction_jobs')
    op.drop_index('ix_extraction_jobs_connection_id', table_name='extraction_jobs')
    op.drop_table('extraction_jobs')
    op.drop_index('ix_extraction_connections_project_id', table_name='extraction_connections')
    op.drop_index('ix_extraction_connections_connector_type', table_name='extraction_connections')
    op.drop_table('extraction_connections')
