"""dataset_versions.preview_json: the snapshot's preview, for temporal reads

Time travel increment 2 (temporal reads). A version now carries the preview
captured when it was published, so reading a dataset "as of" a version shows the
data as it was then rather than the current head. Schema-only (settled decision
#5); versions recorded before this column carry a null preview.

Revision ID: 0039_dataset_version_preview
Revises: 0038_dataset_versions
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0039_dataset_version_preview'
down_revision = '0038_dataset_versions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dataset_versions', sa.Column('preview_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('dataset_versions', 'preview_json')
