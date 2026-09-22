"""Identity core: contact fields, session versioning, API tokens, one-time codes

Adds what a company's first security review checks: a person can change their
own password (and an admin can force a reset) with every existing session
ended at once (`token_version`); scripts authenticate with revocable API
tokens instead of a user's password; and an invited account activates itself
with a one-time code. `email` and `display_name` give an account a human face.

Revision ID: 0031_identity_core
Revises: 0030_ingest_specs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0031_identity_core'
down_revision = '0030_ingest_specs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('display_name', sa.String(length=120), nullable=True))
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('prefix', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('scope', sa.String(length=16), nullable=False, server_default='read'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_api_tokens_user', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_hash', 'api_tokens', ['token_hash'], unique=True)

    op.create_table(
        'auth_codes',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('purpose', sa.String(length=16), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_auth_codes_user', 'auth_codes', ['user_id'])
    op.create_index('ix_auth_codes_hash', 'auth_codes', ['code_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('auth_codes')
    op.drop_table('api_tokens')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'display_name')
    op.drop_column('users', 'email')
