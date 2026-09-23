"""Second-factor authentication: TOTP secret and recovery codes per user

A password proves knowledge; the second factor proves possession. This table
holds a person's TOTP secret and their hashed, single-use recovery codes, with
an `activated` flag so an enrolment that was started but never confirmed with a
live code cannot lock the owner out on their next sign-in.

Revision ID: 0034_user_mfa
Revises: 0033_upload_sessions
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0034_user_mfa'
down_revision = '0033_upload_sessions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_mfa',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('secret', sa.String(length=64), nullable=False),
        sa.Column('activated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recovery_codes_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_user_mfa_user', 'user_mfa', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_mfa_user', table_name='user_mfa')
    op.drop_table('user_mfa')
