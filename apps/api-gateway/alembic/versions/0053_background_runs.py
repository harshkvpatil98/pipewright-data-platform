"""runs the worker does instead of the request

Adoption-readiness A7 (X3): a large upload and a database copy are queued as
runs that the background worker claims; these columns hold what to do and
the claiming worker's lease.

Revision ID: 0053_background_runs
Revises: 0052_rate_limits
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0053_background_runs'
down_revision = '0052_rate_limits'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('pipeline_runs', sa.Column('request_json', sa.JSON(), nullable=True))
    op.add_column('pipeline_runs', sa.Column('claim_owner_id', sa.String(length=128), nullable=True))
    op.add_column('pipeline_runs', sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('pipeline_runs', 'claim_expires_at')
    op.drop_column('pipeline_runs', 'claim_owner_id')
    op.drop_column('pipeline_runs', 'request_json')
