"""saved statistical tests and runs

Revision ID: 0007_saved_statistical_tests
Revises: 0006_transformations_and_lineage
Create Date: 2026-04-08 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_saved_statistical_tests"
down_revision: str | None = "0006_transformations_and_lineage"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_statistical_tests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("left_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("right_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("test_type", sa.String(length=32), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=False),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["left_dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["right_dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_statistical_tests_project_id", "saved_statistical_tests", ["project_id"], unique=False)
    op.create_index(
        "ix_saved_statistical_tests_left_dataset_id", "saved_statistical_tests", ["left_dataset_id"], unique=False
    )
    op.create_index(
        "ix_saved_statistical_tests_right_dataset_id", "saved_statistical_tests", ["right_dataset_id"], unique=False
    )

    op.create_table(
        "saved_statistical_test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("saved_test_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("executed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["saved_test_id"], ["saved_statistical_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["executed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_saved_statistical_test_runs_saved_test_id", "saved_statistical_test_runs", ["saved_test_id"], unique=False
    )
    op.create_index(
        "ix_saved_statistical_test_runs_project_id", "saved_statistical_test_runs", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_saved_statistical_test_runs_project_id", table_name="saved_statistical_test_runs")
    op.drop_index("ix_saved_statistical_test_runs_saved_test_id", table_name="saved_statistical_test_runs")
    op.drop_table("saved_statistical_test_runs")
    op.drop_index("ix_saved_statistical_tests_right_dataset_id", table_name="saved_statistical_tests")
    op.drop_index("ix_saved_statistical_tests_left_dataset_id", table_name="saved_statistical_tests")
    op.drop_index("ix_saved_statistical_tests_project_id", table_name="saved_statistical_tests")
    op.drop_table("saved_statistical_tests")
