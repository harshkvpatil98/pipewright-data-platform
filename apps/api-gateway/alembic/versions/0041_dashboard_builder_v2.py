"""dashboard builder v2: text tiles and auto-refresh

A dashboard tile could only be a chart. Tiles gain a `kind` (`chart` or
`text`), an optional `title` and a `body`, and `chart_id` becomes nullable so a
text tile needs no chart. Dashboards gain `refresh_seconds` (null = manual
refresh only). Schema only; every existing tile is a chart tile.

Revision ID: 0041_dashboard_builder_v2
Revises: 0040_dataset_version_lifecycle
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0041_dashboard_builder_v2'
down_revision = '0040_dataset_version_lifecycle'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('dashboard_tiles') as batch:
        batch.alter_column('chart_id', existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column('kind', sa.String(length=16), nullable=False, server_default='chart'))
        batch.add_column(sa.Column('title', sa.String(length=160), nullable=True))
        batch.add_column(sa.Column('body', sa.Text(), nullable=True))
    op.add_column('dashboards', sa.Column('refresh_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('dashboards', 'refresh_seconds')
    op.execute("DELETE FROM dashboard_tiles WHERE chart_id IS NULL")
    with op.batch_alter_table('dashboard_tiles') as batch:
        batch.drop_column('body')
        batch.drop_column('title')
        batch.drop_column('kind')
        batch.alter_column('chart_id', existing_type=sa.Uuid(), nullable=False)
