"""users.auth_source: local vs directory-managed (SSO) accounts

The SCIM-lite deactivate-on-absence sync must only ever touch accounts the
identity provider owns. This column records who owns an account so a local
admin can never be swept when they are (correctly) absent from the directory.

Revision ID: 0036_user_auth_source
Revises: 0035_sso_login_states
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0036_user_auth_source'
down_revision = '0035_sso_login_states'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('auth_source', sa.String(length=16), nullable=False, server_default='local'),
    )


def downgrade() -> None:
    op.drop_column('users', 'auth_source')
