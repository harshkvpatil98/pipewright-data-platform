"""recipe management: parameters, branches, saved templates, column metadata

Roadmap Phase 16 (E1, T6): a recipe's parameters, the recipe a branch was
made from and the steps it was made from (for merging back), templates a
project saves for itself, and the tags and classifications a recipe's
metadata steps give its output's columns.

Revision ID: 0066_recipe_management
Revises: 0065_incremental_runs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0066_recipe_management'
down_revision = '0065_incremental_runs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transformation_pipelines') as batch:
        batch.add_column(sa.Column('parameters_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('branched_from_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('branch_base_json', sa.JSON(), nullable=True))
        batch.create_foreign_key('fk_transformation_pipelines_branched_from', 'transformation_pipelines',
                                 ['branched_from_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'recipe_templates',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('steps_json', sa.JSON(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'name', name='uq_recipe_templates_project_name'),
    )
    op.create_index('ix_recipe_templates_project_id', 'recipe_templates', ['project_id'])

    with op.batch_alter_table('catalog_annotations') as batch:
        batch.add_column(sa.Column('column_tags_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('column_classes_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('catalog_annotations') as batch:
        batch.drop_column('column_classes_json')
        batch.drop_column('column_tags_json')
    op.drop_index('ix_recipe_templates_project_id', table_name='recipe_templates')
    op.drop_table('recipe_templates')
    with op.batch_alter_table('transformation_pipelines') as batch:
        batch.drop_constraint('fk_transformation_pipelines_branched_from', type_='foreignkey')
        batch.drop_column('branch_base_json')
        batch.drop_column('branched_from_id')
        batch.drop_column('parameters_json')
