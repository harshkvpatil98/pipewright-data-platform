"""project environments and approval requirement

Environments are separate projects rather than a flag on every resource. A flag
means every query in the platform has to remember to filter by it, and the one
query that forgets is the one that publishes test data to production.

Revision ID: 0023_project_environments
Revises: 0022_governance
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0023_project_environments'
down_revision = '0022_governance'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("environment", sa.String(length=16), nullable=False, server_default="development"),
    )
    op.add_column(
        "projects",
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "projects",
        sa.Column("promoted_from_project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_promoted_from",
        "projects",
        "projects",
        ["promoted_from_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_environment", "projects", ["environment"])


def downgrade() -> None:
    op.drop_index("ix_projects_environment", table_name="projects")
    op.drop_constraint("fk_projects_promoted_from", "projects", type_="foreignkey")
    op.drop_column("projects", "promoted_from_project_id")
    op.drop_column("projects", "requires_approval")
    op.drop_column("projects", "environment")
