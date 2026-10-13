"""organisation network allow-lists

Adoption-readiness A6 (W5): an organisation can name the addresses and ranges
its people may connect from. Sign-in and every request from elsewhere are
refused, API tokens included. NULL (the default) means anywhere.

Revision ID: 0049_organisation_networks
Revises: 0048_imports_from_any_connector
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0049_organisation_networks'
down_revision = '0048_imports_from_any_connector'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organisations', sa.Column('allowed_networks_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('organisations', 'allowed_networks_json')
