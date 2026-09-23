"""dataset_versions lifecycle state and dataset_version_pins

Time travel (Phase 18) §4: the concurrent garbage-collection protocol needs two
things the schema did not have. A version gains a retention lifecycle
(`retention_state`: active → pending_delete → pruned, with `delete_after` as the
lease, `pruned_at` when the metadata was tombstoned and `artifact_removed_at`
when the bytes actually went) so a sweep can mark, wait, re-validate and delete
in separately durable steps. And `dataset_version_pins` records who is holding a
version open -- a rollback copying it, a replay reading it -- durably, before
any bytes are read, so a sweep in another session can see the pin. Schema only
(settled decision #5); every existing version is `active`.

Revision ID: 0040_dataset_version_lifecycle
Revises: 0039_dataset_version_preview
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0040_dataset_version_lifecycle'
down_revision = '0039_dataset_version_preview'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'dataset_versions',
        sa.Column('retention_state', sa.String(length=16), nullable=False, server_default='active'),
    )
    op.add_column('dataset_versions', sa.Column('delete_after', sa.DateTime(timezone=True), nullable=True))
    op.add_column('dataset_versions', sa.Column('pruned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'dataset_versions', sa.Column('artifact_removed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_dataset_versions_retention_state', 'dataset_versions', ['retention_state'])

    op.create_table(
        'dataset_version_pins',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
        sa.Column('holder_kind', sa.String(length=32), nullable=False),
        sa.Column('holder_id', sa.Uuid(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dataset_version_pins_version_id', 'dataset_version_pins', ['dataset_version_id'])
    op.create_index(
        'ix_dataset_version_pins_holder', 'dataset_version_pins', ['holder_kind', 'holder_id']
    )


def downgrade() -> None:
    op.drop_index('ix_dataset_version_pins_holder', table_name='dataset_version_pins')
    op.drop_index('ix_dataset_version_pins_version_id', table_name='dataset_version_pins')
    op.drop_table('dataset_version_pins')
    op.drop_index('ix_dataset_versions_retention_state', table_name='dataset_versions')
    op.drop_column('dataset_versions', 'artifact_removed_at')
    op.drop_column('dataset_versions', 'pruned_at')
    op.drop_column('dataset_versions', 'delete_after')
    op.drop_column('dataset_versions', 'retention_state')
