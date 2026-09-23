"""metrics: the semantic layer

A metric is one definition of a number -- an aggregation over a column or a
formula, with the filters that belong to it and the dimensions it may be cut
by -- owned, described, and resolved at compute time by every chart that names
it, so changing the definition changes it everywhere at once. saved_charts
gains a nullable metric_id; a chart that names a metric takes its measure and
filters from the metric rather than from its own query. Schema only.

Revision ID: 0044_metrics
Revises: 0043_extraction_job_steps
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0044_metrics'
down_revision = '0043_extraction_job_steps'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'metrics',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('slug', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('aggregation', sa.String(length=24), nullable=False),
        sa.Column('column', sa.String(length=200), nullable=True),
        sa.Column('formula', sa.Text(), nullable=True),
        sa.Column('filters_json', sa.JSON(), nullable=True),
        sa.Column('dimensions_json', sa.JSON(), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'slug', name='uq_metrics_project_slug'),
    )
    op.create_index('ix_metrics_project_id', 'metrics', ['project_id'])
    op.create_index('ix_metrics_dataset_id', 'metrics', ['dataset_id'])
    op.add_column('saved_charts', sa.Column('metric_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_saved_charts_metric_id', 'saved_charts', 'metrics', ['metric_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_saved_charts_metric_id', 'saved_charts', ['metric_id'])


def downgrade() -> None:
    op.drop_index('ix_saved_charts_metric_id', table_name='saved_charts')
    op.drop_constraint('fk_saved_charts_metric_id', 'saved_charts', type_='foreignkey')
    op.drop_column('saved_charts', 'metric_id')
    op.drop_index('ix_metrics_dataset_id', table_name='metrics')
    op.drop_index('ix_metrics_project_id', table_name='metrics')
    op.drop_table('metrics')
