"""run limits: who started a run, and a project's own limit on runs at once

Roadmap Phase 22 (D2, O8): a run records whether a person, a schedule, a
backfill or a workflow started it, which decides what the worker takes
first and what counts towards the project's runs at once; a project may
set its own limit instead of the deployment's.

Revision ID: 0064_run_limits
Revises: 0063_statistics
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0064_run_limits'
down_revision = '0063_statistics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('pipeline_runs') as batch:
        batch.add_column(sa.Column('origin', sa.String(length=16), server_default='person', nullable=False))
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('max_runs_at_once', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('max_runs_at_once')
    with op.batch_alter_table('pipeline_runs') as batch:
        batch.drop_column('origin')
