"""workflow task retries, resumed runs and attempt counts

Adoption-readiness A7 (X4): a task can be tried again with a backoff; a failed
run can be started again from where it failed, reusing what succeeded; and a
task's record says how many attempts it took.

Revision ID: 0051_workflow_retries
Revises: 0050_weekly_summaries
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0051_workflow_retries'
down_revision = '0050_weekly_summaries'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('workflow_nodes', sa.Column('retries', sa.Integer(), nullable=False, server_default='0'))
    op.add_column(
        'workflow_nodes', sa.Column('retry_delay_seconds', sa.Integer(), nullable=False, server_default='30')
    )
    op.add_column('workflow_node_runs', sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('workflow_runs', sa.Column('resumed_from_run_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_workflow_runs_resumed_from', 'workflow_runs', 'workflow_runs',
        ['resumed_from_run_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_workflow_runs_resumed_from', 'workflow_runs', type_='foreignkey')
    op.drop_column('workflow_runs', 'resumed_from_run_id')
    op.drop_column('workflow_node_runs', 'attempts')
    op.drop_column('workflow_nodes', 'retry_delay_seconds')
    op.drop_column('workflow_nodes', 'retries')
