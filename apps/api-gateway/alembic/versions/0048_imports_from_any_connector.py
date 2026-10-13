"""imports from any connector that can read

Adoption-readiness A4 (U2): an import's source can be any connector in the
catalogue that declares `read`, not only the three SQL databases. Such an
import names what to read as the stream the connector listed (name, namespace,
kind, detail), stored here; NULL means everything the connection returns.

Revision ID: 0048_imports_from_any_connector
Revises: 0047_one_dataset_per_producer
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0048_imports_from_any_connector'
down_revision = '0047_one_dataset_per_producer'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('extraction_jobs', sa.Column('stream_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('extraction_jobs', 'stream_json')
