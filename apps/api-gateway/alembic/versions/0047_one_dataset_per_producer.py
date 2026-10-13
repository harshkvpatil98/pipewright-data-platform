"""one dataset per recipe: the dataset its runs write to

Adoption-readiness A4 (U1): a recipe's runs, like an import's, used to create
a new dataset each time. `output_dataset_id` names the dataset a recipe writes;
each run adds a version to it. Existing recipes are pointed at their newest
non-replay output, so the next run continues that dataset rather than starting
another. Imports already record their dataset (`extraction_jobs.target_dataset_id`)
and need no change here.

Revision ID: 0047_one_dataset_per_producer
Revises: 0046_notification_grouping
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0047_one_dataset_per_producer'
down_revision = '0046_notification_grouping'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'transformation_pipelines',
        sa.Column('output_dataset_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_transformation_pipelines_output_dataset_id',
        'transformation_pipelines',
        'datasets',
        ['output_dataset_id'],
        ['id'],
        ondelete='SET NULL',
    )
    # A replay publishes beside the original on purpose ("<name> · replay"), so
    # it is never the recipe's output.
    op.execute(
        """
        UPDATE transformation_pipelines
        SET output_dataset_id = (
            SELECT datasets.id FROM datasets
            WHERE datasets.created_from_pipeline_id = transformation_pipelines.id
              AND datasets.name NOT LIKE '% · replay'
            ORDER BY datasets.created_at DESC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_transformation_pipelines_output_dataset_id', 'transformation_pipelines', type_='foreignkey'
    )
    op.drop_column('transformation_pipelines', 'output_dataset_id')
