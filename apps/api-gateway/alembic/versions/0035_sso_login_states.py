"""SSO login state: the short-lived state of one in-flight OIDC sign-in

The authorization redirect and the callback are two requests; the second proves
it belongs to the first via the `state` and the PKCE `code_verifier`. Storing
them here (not in memory) lets the callback land on any gateway process and
survive a restart mid-sign-in. Rows are one-time and swept by age.

Revision ID: 0035_sso_login_states
Revises: 0034_user_mfa
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0035_sso_login_states'
down_revision = '0034_user_mfa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sso_login_states',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('state', sa.String(length=64), nullable=False),
        sa.Column('code_verifier', sa.String(length=128), nullable=False),
        sa.Column('nonce', sa.String(length=64), nullable=False),
        sa.Column('next_path', sa.String(length=512), nullable=False, server_default='/'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_sso_login_states_state', 'sso_login_states', ['state'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_sso_login_states_state', table_name='sso_login_states')
    op.drop_table('sso_login_states')
