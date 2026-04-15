"""project ownership and pipeline runs

Revision ID: 0004_project_ownership_and_pipeline_runs
Revises: 0003_auth_users
Create Date: 2026-04-02 00:00:01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_project_ownership_and_pipeline_runs"
down_revision: str | None = "0003_auth_users"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_projects_owner_user_id", "projects", ["owner_user_id"], unique=False)
    op.create_foreign_key(
        "fk_projects_owner_user_id_users",
        "projects",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("logs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_project_id", "pipeline_runs", ["project_id"], unique=False)
    op.create_index(
        "ix_pipeline_runs_triggered_by_user_id",
        "pipeline_runs",
        ["triggered_by_user_id"],
        unique=False,
    )
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"], unique=False)
    op.create_index("ix_pipeline_runs_run_type", "pipeline_runs", ["run_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_run_type", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_triggered_by_user_id", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_project_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    op.drop_constraint("fk_projects_owner_user_id_users", "projects", type_="foreignkey")
    op.drop_index("ix_projects_owner_user_id", table_name="projects")
    op.drop_column("projects", "owner_user_id")
