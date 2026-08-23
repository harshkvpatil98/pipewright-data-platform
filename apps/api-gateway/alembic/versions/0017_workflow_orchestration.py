"""workflow orchestration: workflows, nodes, edges, runs, node runs

Adds the DAG definition tables plus the run queue. `workflow_runs` doubles as the
queue: a worker claims a row with FOR UPDATE SKIP LOCKED and holds a lease, so
runs execute outside the request cycle and survive a worker dying.

Note: autogenerate also reports pre-existing JSONB->JSON and users.username
differences unrelated to this change; those are deliberately excluded.

Revision ID: 0017_workflow_orchestration
Revises: 0016_list_query_composite_indexes
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0017_workflow_orchestration'
down_revision = '0016_list_query_composite_indexes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('workflows',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('trigger_type', sa.String(length=24), nullable=False),
    sa.Column('cron_expression', sa.String(length=120), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('default_parameters', sa.JSON(), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_status', sa.String(length=24), nullable=True),
    sa.Column('execution_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workflows_next_run_at', 'workflows', ['next_run_at'], unique=False)
    op.create_index('ix_workflows_project_enabled', 'workflows', ['project_id', 'enabled'], unique=False)
    op.create_index('ix_workflows_project_id', 'workflows', ['project_id'], unique=False)
    op.create_table('workflow_edges',
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('from_node_key', sa.String(length=64), nullable=False),
    sa.Column('to_node_key', sa.String(length=64), nullable=False),
    sa.Column('condition', sa.String(length=24), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'from_node_key', 'to_node_key', name='uq_workflow_edges_pair')
    )
    op.create_index('ix_workflow_edges_workflow_id', 'workflow_edges', ['workflow_id'], unique=False)
    op.create_table('workflow_nodes',
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('node_key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('node_type', sa.String(length=32), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('continue_on_failure', sa.Boolean(), nullable=False),
    sa.Column('position_x', sa.Float(), nullable=False),
    sa.Column('position_y', sa.Float(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'node_key', name='uq_workflow_nodes_workflow_key')
    )
    op.create_index('ix_workflow_nodes_project_id', 'workflow_nodes', ['project_id'], unique=False)
    op.create_index('ix_workflow_nodes_workflow_id', 'workflow_nodes', ['workflow_id'], unique=False)
    op.create_table('workflow_runs',
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('trigger', sa.String(length=24), nullable=False),
    sa.Column('parameters_json', sa.JSON(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claim_owner_id', sa.String(length=128), nullable=True),
    sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('triggered_by_user_id', sa.UUID(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('nodes_total', sa.Integer(), nullable=False),
    sa.Column('nodes_succeeded', sa.Integer(), nullable=False),
    sa.Column('nodes_failed', sa.Integer(), nullable=False),
    sa.Column('nodes_skipped', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workflow_runs_project_created', 'workflow_runs', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_workflow_runs_status_queued', 'workflow_runs', ['status', 'queued_at'], unique=False)
    op.create_index('ix_workflow_runs_workflow_id', 'workflow_runs', ['workflow_id'], unique=False)
    op.create_table('workflow_node_runs',
    sa.Column('workflow_run_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('node_key', sa.String(length=64), nullable=False),
    sa.Column('node_name', sa.String(length=160), nullable=False),
    sa.Column('node_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('output_json', sa.JSON(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('skip_reason', sa.Text(), nullable=True),
    sa.Column('pipeline_run_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workflow_node_runs_project_id', 'workflow_node_runs', ['project_id'], unique=False)
    op.create_index('ix_workflow_node_runs_run_id', 'workflow_node_runs', ['workflow_run_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_workflow_node_runs_project_id', table_name='workflow_node_runs')
    op.drop_index('ix_workflow_node_runs_run_id', table_name='workflow_node_runs')
    op.drop_table('workflow_node_runs')
    op.drop_index('ix_workflow_runs_status_queued', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_project_created', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_workflow_id', table_name='workflow_runs')
    op.drop_table('workflow_runs')
    op.drop_index('ix_workflow_edges_workflow_id', table_name='workflow_edges')
    op.drop_table('workflow_edges')
    op.drop_index('ix_workflow_nodes_project_id', table_name='workflow_nodes')
    op.drop_index('ix_workflow_nodes_workflow_id', table_name='workflow_nodes')
    op.drop_table('workflow_nodes')
    op.drop_index('ix_workflows_next_run_at', table_name='workflows')
    op.drop_index('ix_workflows_project_enabled', table_name='workflows')
    op.drop_index('ix_workflows_project_id', table_name='workflows')
    op.drop_table('workflows')
