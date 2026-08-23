"""staged write-back change sets

Edits are staged rather than applied so a change can be reviewed, shared, sent
through approval, and discarded. `executed_sql` records what actually ran:
direct writes to a production table without an audit trail would be the worst
thing this platform could ship.

Revision ID: 0027_writeback_change_sets
Revises: 0026_user_preferences
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0027_writeback_change_sets'
down_revision = '0026_user_preferences'
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "writeback_change_sets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), sa.ForeignKey("extraction_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(length=200), nullable=False),
        sa.Column("table_schema", sa.String(length=200), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="Untitled change"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rows_affected", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("executed_sql", sa.JSON(), nullable=True),
        sa.Column("designated_key", sa.JSON(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_writeback_change_sets_project_id", "writeback_change_sets", ["project_id"])
    op.create_index("ix_writeback_change_sets_status", "writeback_change_sets", ["status"])

    op.create_table(
        "writeback_change_set_edits",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("change_set_id", sa.Uuid(as_uuid=True), sa.ForeignKey("writeback_change_sets.id", ondelete="CASCADE"), nullable=False),
        # Explicit, because created_at is the transaction time in Postgres and
        # every edit staged in one request would tie.
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_writeback_change_set_edits_change_set_id",
        "writeback_change_set_edits",
        ["change_set_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_writeback_change_set_edits_change_set_id", table_name="writeback_change_set_edits")
    op.drop_table("writeback_change_set_edits")
    op.drop_index("ix_writeback_change_sets_status", table_name="writeback_change_sets")
    op.drop_index("ix_writeback_change_sets_project_id", table_name="writeback_change_sets")
    op.drop_table("writeback_change_sets")
