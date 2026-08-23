"""per-user interface preferences

A separate table rather than columns on `users`: this grows with the Studio
(grid density, keyboard scheme, column defaults) and none of that belongs in
the identity record.

Stored server-side rather than only in localStorage so someone's setup follows
them between machines, and so the shell can render the correct theme on first
paint instead of flashing the wrong one.

Revision ID: 0026_user_preferences
Revises: 0025_enterprise
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0026_user_preferences'
down_revision = '0025_enterprise'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "system" follows the operating system, and is the default: it is the
        # only value that stays correct when someone changes their OS setting.
        sa.Column("theme", sa.String(length=16), nullable=False, server_default="system"),
        sa.Column(
            "density", sa.String(length=16), nullable=False, server_default="comfortable"
        ),
        sa.Column("extra_json", sa.JSON(), nullable=True),
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
    )
    # Unique, not merely indexed: one preferences row per person, enforced by
    # the database rather than by whichever code path happens to write first.
    op.create_index(
        "ix_user_preferences_user_id", "user_preferences", ["user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")
