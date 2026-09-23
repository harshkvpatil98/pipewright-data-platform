"""SAML login state: the short-lived state of one in-flight SAML sign-in

The redirect to the identity provider and the assertion that comes back are two
requests; the second proves it belongs to the first by returning this
`request_id` in its `InResponseTo`. The row is deleted the moment it is spent,
so the same assertion cannot be replayed. Rows are swept by age.

Revision ID: 0037_saml_login_states
Revises: 0036_user_auth_source
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0037_saml_login_states'
down_revision = '0036_user_auth_source'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saml_login_states',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('next_path', sa.String(length=512), nullable=False, server_default='/'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index(
        'ix_saml_login_states_request_id', 'saml_login_states', ['request_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_saml_login_states_request_id', table_name='saml_login_states')
    op.drop_table('saml_login_states')
