"""API tokens limited to projects and given an expiry; the audit log names the token

Roadmap Phase 23 (E2, X2): a token can be limited to some projects and can
expire, so a script or Terraform holds no more than it needs; each audit
entry made with a token says which.

Revision ID: 0067_scoped_tokens
Revises: 0066_recipe_management
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0067_scoped_tokens'
down_revision = '0066_recipe_management'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('api_tokens') as batch:
        batch.add_column(sa.Column('project_ids_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('audit_entries') as batch:
        batch.add_column(sa.Column('credential', sa.String(length=160), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_entries') as batch:
        batch.drop_column('credential')
    with op.batch_alter_table('api_tokens') as batch:
        batch.drop_column('expires_at')
        batch.drop_column('project_ids_json')
