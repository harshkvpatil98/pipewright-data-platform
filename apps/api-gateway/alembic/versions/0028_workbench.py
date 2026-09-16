"""SQL workbench: saved queries, run history, notebooks

Run history records what was executed and how it went -- never the results.
A workbench runs arbitrary SELECTs against customer databases, so retaining
their output would turn a convenience feature into a second copy of somebody
else's personal data that nobody asked this platform to keep.

Revision ID: 0028_workbench
Revises: 0027_writeback_change_sets
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0028_workbench'
down_revision = '0027_writeback_change_sets'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workbench_saved_queries',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connection_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sql', sa.Text(), nullable=False),
        sa.Column('parameters_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_by_user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_workbench_saved_queries_project_id', 'workbench_saved_queries', ['project_id'])
    # Unique per project: two saved queries called "Daily revenue" is a support
    # ticket waiting to happen.
    op.create_index('ix_workbench_saved_queries_project_name', 'workbench_saved_queries', ['project_id', 'name'], unique=True)

    op.create_table(
        'workbench_query_runs',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connection_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('saved_query_id', sa.Uuid(as_uuid=True), sa.ForeignKey('workbench_saved_queries.id', ondelete='SET NULL'), nullable=True),
        sa.Column('sql', sa.Text(), nullable=False),
        sa.Column('statement_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('wrote', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('succeeded', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('duration_ms', sa.Float(), nullable=False, server_default='0'),
        sa.Column('rows_returned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rows_affected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('run_by_user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_workbench_query_runs_project_created', 'workbench_query_runs', ['project_id', 'created_at'])
    op.create_index('ix_workbench_query_runs_user', 'workbench_query_runs', ['run_by_user_id'])

    op.create_table(
        'workbench_notebooks',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('project_id', sa.Uuid(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connection_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_workbench_notebooks_project_id', 'workbench_notebooks', ['project_id'])

    op.create_table(
        'workbench_notebook_cells',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('notebook_id', sa.Uuid(as_uuid=True), sa.ForeignKey('workbench_notebooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='sql'),
        sa.Column('source', sa.Text(), nullable=False, server_default=''),
        sa.Column('output_name', sa.String(length=120), nullable=True),
        sa.Column('config_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_workbench_notebook_cells_notebook', 'workbench_notebook_cells', ['notebook_id', 'position'])


def downgrade() -> None:
    op.drop_index('ix_workbench_notebook_cells_notebook', table_name='workbench_notebook_cells')
    op.drop_table('workbench_notebook_cells')
    op.drop_index('ix_workbench_notebooks_project_id', table_name='workbench_notebooks')
    op.drop_table('workbench_notebooks')
    op.drop_index('ix_workbench_query_runs_user', table_name='workbench_query_runs')
    op.drop_index('ix_workbench_query_runs_project_created', table_name='workbench_query_runs')
    op.drop_table('workbench_query_runs')
    op.drop_index('ix_workbench_saved_queries_project_name', table_name='workbench_saved_queries')
    op.drop_index('ix_workbench_saved_queries_project_id', table_name='workbench_saved_queries')
    op.drop_table('workbench_saved_queries')
