"""a fingerprint of each task's settings on its run

Adoption-readiness A7: picking a failed workflow run up reuses a task that
succeeded only while its settings are unchanged. The earlier check compared
the workflow's updated_at, which every finished run moves, so a run could
never be picked up on PostgreSQL.

Revision ID: 0054_task_settings_hash
Revises: 0053_background_runs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0054_task_settings_hash'
down_revision = '0053_background_runs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('workflow_node_runs', sa.Column('settings_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('workflow_node_runs', 'settings_hash')
