"""Per-organisation session policy: how long a tenant's sessions last

Null means "use the deployment default". A tenant that has never set a policy
must keep the behaviour it had, so the column cannot have a non-null default --
that would silently impose a policy on every existing organisation.

Revision ID: 0038_org_session_policy
Revises: 0037_saml_login_states
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0038_org_session_policy'
down_revision = '0037_saml_login_states'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'organisations', sa.Column('session_max_minutes', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('organisations', 'session_max_minutes')
