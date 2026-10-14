"""dashboards shown inside other sites, by signed links that run out

Adoption-readiness A8 (Y4): an embed has its own signing secret, an expiry
and a way to turn it off, so a partner can show a dashboard in their own
product without a link that works for ever.

Revision ID: 0057_dashboard_embeds
Revises: 0056_webhook_deliveries
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0057_dashboard_embeds'
down_revision = '0056_webhook_deliveries'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dashboard_embeds',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('dashboard_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('signing_secret', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dashboard_id'], ['dashboards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dashboard_embeds_dashboard_id', 'dashboard_embeds', ['dashboard_id'])


def downgrade() -> None:
    op.drop_index('ix_dashboard_embeds_dashboard_id', table_name='dashboard_embeds')
    op.drop_table('dashboard_embeds')
