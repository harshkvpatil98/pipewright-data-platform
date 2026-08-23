"""data quality rules, results, and schema drift events

Note: autogenerate also reports pre-existing JSONB->JSON and users.username
differences unrelated to this change; those are deliberately excluded.

Revision ID: 0015_data_quality_and_drift
Revises: 0014_extraction_connections_and_jobs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0015_data_quality_and_drift'
down_revision = '0014_extraction_connections_and_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('data_quality_rules',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('dataset_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('rule_type', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=16), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_data_quality_rules_dataset_id', 'data_quality_rules', ['dataset_id'], unique=False)
    op.create_index('ix_data_quality_rules_project_enabled', 'data_quality_rules', ['project_id', 'enabled'], unique=False)
    op.create_index('ix_data_quality_rules_project_id', 'data_quality_rules', ['project_id'], unique=False)
    op.create_table('schema_drift_events',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('dataset_id', sa.UUID(), nullable=True),
    sa.Column('previous_dataset_id', sa.UUID(), nullable=True),
    sa.Column('extraction_job_id', sa.UUID(), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('added_columns', sa.JSON(), nullable=True),
    sa.Column('removed_columns', sa.JSON(), nullable=True),
    sa.Column('type_changes', sa.JSON(), nullable=True),
    sa.Column('acknowledged', sa.Boolean(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['previous_dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_schema_drift_events_dataset_id', 'schema_drift_events', ['dataset_id'], unique=False)
    op.create_index('ix_schema_drift_events_project_ack', 'schema_drift_events', ['project_id', 'acknowledged'], unique=False)
    op.create_index('ix_schema_drift_events_project_id', 'schema_drift_events', ['project_id'], unique=False)
    op.create_index('ix_schema_drift_events_severity', 'schema_drift_events', ['severity'], unique=False)
    op.create_table('data_quality_run_results',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('evaluation_id', sa.UUID(), nullable=False),
    sa.Column('rule_id', sa.UUID(), nullable=True),
    sa.Column('dataset_id', sa.UUID(), nullable=True),
    sa.Column('pipeline_run_id', sa.UUID(), nullable=True),
    sa.Column('rule_name', sa.String(length=160), nullable=False),
    sa.Column('rule_type', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('evaluated_rows', sa.Integer(), nullable=False),
    sa.Column('failed_rows', sa.Integer(), nullable=False),
    sa.Column('failure_rate', sa.Float(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('details_json', sa.JSON(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['data_quality_rules.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dq_run_results_dataset_id', 'data_quality_run_results', ['dataset_id'], unique=False)
    op.create_index('ix_dq_run_results_evaluation_id', 'data_quality_run_results', ['evaluation_id'], unique=False)
    op.create_index('ix_dq_run_results_project_id', 'data_quality_run_results', ['project_id'], unique=False)
    op.create_index('ix_dq_run_results_rule_id', 'data_quality_run_results', ['rule_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_dq_run_results_evaluation_id', table_name='data_quality_run_results')
    op.drop_index('ix_dq_run_results_rule_id', table_name='data_quality_run_results')
    op.drop_index('ix_dq_run_results_dataset_id', table_name='data_quality_run_results')
    op.drop_index('ix_dq_run_results_project_id', table_name='data_quality_run_results')
    op.drop_table('data_quality_run_results')
    op.drop_index('ix_schema_drift_events_project_ack', table_name='schema_drift_events')
    op.drop_index('ix_schema_drift_events_severity', table_name='schema_drift_events')
    op.drop_index('ix_schema_drift_events_dataset_id', table_name='schema_drift_events')
    op.drop_index('ix_schema_drift_events_project_id', table_name='schema_drift_events')
    op.drop_table('schema_drift_events')
    op.drop_index('ix_data_quality_rules_project_enabled', table_name='data_quality_rules')
    op.drop_index('ix_data_quality_rules_dataset_id', table_name='data_quality_rules')
    op.drop_index('ix_data_quality_rules_project_id', table_name='data_quality_rules')
    op.drop_table('data_quality_rules')
