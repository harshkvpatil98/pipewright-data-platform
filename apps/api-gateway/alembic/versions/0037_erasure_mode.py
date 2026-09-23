"""erasure_requests.mode: correction vs destructive erasure

Distinguishes an ordinary forward-moving correction (live data cleared, history
readable) from an authorised destructive erasure (also removed from historical
artifacts). Pre-work for P7's immutable history; the status column now also
carries partial/blocked so an erasure never reports success while data remains.

Revision ID: 0037_erasure_mode
Revises: 0036_user_auth_source
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0037_erasure_mode'
down_revision = '0036_user_auth_source'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'erasure_requests',
        sa.Column('mode', sa.String(length=16), nullable=False, server_default='correction'),
    )


def downgrade() -> None:
    op.drop_column('erasure_requests', 'mode')
