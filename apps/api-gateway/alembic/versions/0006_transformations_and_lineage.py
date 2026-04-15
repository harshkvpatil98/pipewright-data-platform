"""transformations and lineage

Revision ID: 0006_transformations_and_lineage
Revises: 0005_dataset_ingestion_fields
Create Date: 2026-04-07 00:00:03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_transformations_and_lineage"
down_revision: str | None = "0005_dataset_ingestion_fields"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transformation_pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transformation_pipelines_project_id", "transformation_pipelines", ["project_id"], unique=False)
    op.create_index("ix_transformation_pipelines_base_dataset_id", "transformation_pipelines", ["base_dataset_id"], unique=False)

    op.add_column("datasets", sa.Column("parent_dataset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("datasets", sa.Column("created_from_pipeline_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("datasets", sa.Column("is_derived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_datasets_parent_dataset_id", "datasets", ["parent_dataset_id"], unique=False)
    op.create_index("ix_datasets_created_from_pipeline_id", "datasets", ["created_from_pipeline_id"], unique=False)
    op.create_index("ix_datasets_is_derived", "datasets", ["is_derived"], unique=False)
    op.create_foreign_key(
        "fk_datasets_parent_dataset_id_datasets",
        "datasets",
        "datasets",
        ["parent_dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_datasets_created_from_pipeline_id_transformation_pipelines",
        "datasets",
        "transformation_pipelines",
        ["created_from_pipeline_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("pipeline_runs", sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_pipeline_runs_pipeline_id", "pipeline_runs", ["pipeline_id"], unique=False)
    op.create_foreign_key(
        "fk_pipeline_runs_pipeline_id_transformation_pipelines",
        "pipeline_runs",
        "transformation_pipelines",
        ["pipeline_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pipeline_runs_pipeline_id_transformation_pipelines", "pipeline_runs", type_="foreignkey")
    op.drop_index("ix_pipeline_runs_pipeline_id", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "pipeline_id")

    op.drop_constraint("fk_datasets_created_from_pipeline_id_transformation_pipelines", "datasets", type_="foreignkey")
    op.drop_constraint("fk_datasets_parent_dataset_id_datasets", "datasets", type_="foreignkey")
    op.drop_index("ix_datasets_is_derived", table_name="datasets")
    op.drop_index("ix_datasets_created_from_pipeline_id", table_name="datasets")
    op.drop_index("ix_datasets_parent_dataset_id", table_name="datasets")
    op.drop_column("datasets", "is_derived")
    op.drop_column("datasets", "created_from_pipeline_id")
    op.drop_column("datasets", "parent_dataset_id")

    op.drop_index("ix_transformation_pipelines_base_dataset_id", table_name="transformation_pipelines")
    op.drop_index("ix_transformation_pipelines_project_id", table_name="transformation_pipelines")
    op.drop_table("transformation_pipelines")
