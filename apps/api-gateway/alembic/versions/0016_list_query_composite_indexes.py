"""composite indexes for project-scoped list queries

The dataset and run list endpoints filter by project_id and sort by created_at
descending. The existing single-column project_id indexes let Postgres find the
rows but still require a sort; a composite (project_id, created_at DESC) index
satisfies both the filter and the ordering, so the sort disappears from the plan.

Revision ID: 0016_list_query_composite_indexes
Revises: 0015_data_quality_and_drift
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0016_list_query_composite_indexes'
down_revision = '0015_data_quality_and_drift'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_datasets_project_created',
        'datasets',
        ['project_id', sa.text('created_at DESC')],
        unique=False,
    )
    op.create_index(
        'ix_pipeline_runs_project_created',
        'pipeline_runs',
        ['project_id', sa.text('created_at DESC')],
        unique=False,
    )
    op.create_index(
        'ix_transformation_pipelines_project_updated',
        'transformation_pipelines',
        ['project_id', sa.text('updated_at DESC')],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_transformation_pipelines_project_updated', table_name='transformation_pipelines')
    op.drop_index('ix_pipeline_runs_project_created', table_name='pipeline_runs')
    op.drop_index('ix_datasets_project_created', table_name='datasets')
