"""dataset ingestion fields

Revision ID: 0005_dataset_ingestion_fields
Revises: 0004_project_ownership_and_pipeline_runs
Create Date: 2026-04-02 00:00:02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_dataset_ingestion_fields"
down_revision: str | None = "0004_project_ownership_and_pipeline_runs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("datasets", sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("datasets", sa.Column("file_name", sa.String(length=255), nullable=True))
    op.add_column("datasets", sa.Column("file_path", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("file_type", sa.String(length=16), nullable=True))
    op.add_column("datasets", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    op.add_column("datasets", sa.Column("ingestion_status", sa.String(length=32), nullable=False, server_default="pending"))
    op.add_column("datasets", sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("datasets", sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("datasets", sa.Column("preview_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("datasets", sa.Column("ingestion_error", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("last_profiled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_datasets_uploaded_by_user_id", "datasets", ["uploaded_by_user_id"], unique=False)
    op.create_index("ix_datasets_pipeline_run_id", "datasets", ["pipeline_run_id"], unique=False)
    op.create_index("ix_datasets_ingestion_status", "datasets", ["ingestion_status"], unique=False)

    op.create_foreign_key(
        "fk_datasets_uploaded_by_user_id_users",
        "datasets",
        "users",
        ["uploaded_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_datasets_pipeline_run_id_pipeline_runs",
        "datasets",
        "pipeline_runs",
        ["pipeline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_datasets_pipeline_run_id_pipeline_runs", "datasets", type_="foreignkey")
    op.drop_constraint("fk_datasets_uploaded_by_user_id_users", "datasets", type_="foreignkey")
    op.drop_index("ix_datasets_ingestion_status", table_name="datasets")
    op.drop_index("ix_datasets_pipeline_run_id", table_name="datasets")
    op.drop_index("ix_datasets_uploaded_by_user_id", table_name="datasets")
    op.drop_column("datasets", "last_profiled_at")
    op.drop_column("datasets", "ingestion_error")
    op.drop_column("datasets", "preview_json")
    op.drop_column("datasets", "profile_json")
    op.drop_column("datasets", "schema_json")
    op.drop_column("datasets", "ingestion_status")
    op.drop_column("datasets", "file_size_bytes")
    op.drop_column("datasets", "file_type")
    op.drop_column("datasets", "file_path")
    op.drop_column("datasets", "file_name")
    op.drop_column("datasets", "pipeline_run_id")
    op.drop_column("datasets", "uploaded_by_user_id")
