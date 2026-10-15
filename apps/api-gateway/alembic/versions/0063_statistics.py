"""statistics: what is known about dataset versions and connected tables

Roadmap Phase 22 (D2, O1): each dataset version's statistics, written with
it; and per table a connection reads, its row count and per-column
statistics, how they were got and when, for estimating plans.

Revision ID: 0063_statistics
Revises: 0062_live_data
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0063_statistics'
down_revision = '0062_live_data'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('dataset_versions') as batch:
        batch.add_column(sa.Column('statistics_json', sa.JSON(), nullable=True))
    op.create_table(
        'table_statistics',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('connection_id', sa.Uuid(), sa.ForeignKey('extraction_connections.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('schema_name', sa.String(length=160), server_default='', nullable=False),
        sa.Column('table_name', sa.String(length=320), nullable=False),
        sa.Column('method', sa.String(length=80), nullable=False),
        sa.Column('row_count', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('stats_json', sa.JSON(), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('connection_id', 'schema_name', 'table_name', name='uq_table_statistics_table'),
    )


def downgrade() -> None:
    op.drop_table('table_statistics')
    with op.batch_alter_table('dataset_versions') as batch:
        batch.drop_column('statistics_json')
