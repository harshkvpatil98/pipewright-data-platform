"""incremental runs: how a recipe's runs compute

Roadmap Phase 22 (D2, O7): every row each time, only rows added at the end
since the last run, or only the partitions of a chosen column whose rows
changed.

Revision ID: 0065_incremental_runs
Revises: 0064_run_limits
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0065_incremental_runs'
down_revision = '0064_run_limits'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transformation_pipelines') as batch:
        batch.add_column(sa.Column('incremental_mode', sa.String(length=16), server_default='full', nullable=False))
        batch.add_column(sa.Column('partition_column', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('transformation_pipelines') as batch:
        batch.drop_column('partition_column')
        batch.drop_column('incremental_mode')
