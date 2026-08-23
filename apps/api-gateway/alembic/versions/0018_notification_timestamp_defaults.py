"""restore server defaults on notification timestamps

`TimestampMixin` declares created_at/updated_at with `server_default=func.now()`,
and every table created from it has that default -- except the two added in
migration 0011 and 0012, where the server default was omitted while the columns
stayed NOT NULL.

The ORM omits these columns on insert precisely because it expects the database
to fill them, so any attempt to write a notification failed with a not-null
violation. In-app notifications have therefore never persisted a row. This
aligns the two tables with the rest of the schema.

Revision ID: 0018_notification_timestamp_defaults
Revises: 0017_workflow_orchestration
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0018_notification_timestamp_defaults'
down_revision = '0017_workflow_orchestration'
branch_labels = None
depends_on = None

_TABLES = ("user_notifications", "external_notification_targets")
_COLUMNS = ("created_at", "updated_at")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=sa.text("now()"),
            )


def downgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=None,
            )
