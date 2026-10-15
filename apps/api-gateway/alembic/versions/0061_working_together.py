"""working together: recipe revisions, a shared copy, presence and threads

Roadmap Phase 21 (C2): a recipe's revision and stable step ids, so a save
never writes over someone else's; the shared working copy and the changes
merged into it; who has a recipe open; replies and a cell to be about on
comments.

Revision ID: 0061_working_together
Revises: 0060_data_contracts
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0061_working_together'
down_revision = '0060_data_contracts'
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        'transformation_pipelines',
        sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    )
    op.add_column('transformation_pipelines', sa.Column('step_ids_json', sa.JSON(), nullable=True))
    op.add_column('transformation_pipelines', sa.Column('revised_by_user_id', sa.Uuid(), nullable=True))
    op.add_column('transformation_pipelines', sa.Column('revised_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_transformation_pipelines_revised_by_user_id',
        'transformation_pipelines',
        'users',
        ['revised_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'recipe_shared_copies',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('pipeline_id', sa.Uuid(), nullable=False),
        sa.Column('epoch', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('doc_json', sa.JSON(), nullable=False),
        sa.Column('reset_reason', sa.Text(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['transformation_pipelines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id', name='uq_recipe_shared_copies_pipeline'),
    )

    op.create_table(
        'recipe_edit_batches',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pipeline_id', sa.Uuid(), nullable=False),
        sa.Column('epoch', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('ops_json', sa.JSON(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(['pipeline_id'], ['transformation_pipelines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id', 'seq', name='uq_recipe_edit_batches_seq'),
    )
    op.create_index('ix_recipe_edit_batches_pipeline_seq', 'recipe_edit_batches', ['pipeline_id', 'seq'])

    op.create_table(
        'presence',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('focus_json', sa.JSON(), nullable=True),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('target_type', 'target_id', 'client_id', name='uq_presence_client'),
    )
    op.create_index('ix_presence_target_seen', 'presence', ['target_type', 'target_id', 'seen_at'])

    op.add_column('comments', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.add_column('comments', sa.Column('anchor_json', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_comments_parent_id', 'comments', 'comments', ['parent_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_comments_parent_id', 'comments', ['parent_id'])


def downgrade() -> None:
    op.drop_index('ix_comments_parent_id', table_name='comments')
    op.drop_constraint('fk_comments_parent_id', 'comments', type_='foreignkey')
    op.drop_column('comments', 'anchor_json')
    op.drop_column('comments', 'parent_id')
    op.drop_index('ix_presence_target_seen', table_name='presence')
    op.drop_table('presence')
    op.drop_index('ix_recipe_edit_batches_pipeline_seq', table_name='recipe_edit_batches')
    op.drop_table('recipe_edit_batches')
    op.drop_table('recipe_shared_copies')
    op.drop_constraint(
        'fk_transformation_pipelines_revised_by_user_id', 'transformation_pipelines', type_='foreignkey'
    )
    op.drop_column('transformation_pipelines', 'revised_at')
    op.drop_column('transformation_pipelines', 'revised_by_user_id')
    op.drop_column('transformation_pipelines', 'step_ids_json')
    op.drop_column('transformation_pipelines', 'revision')
