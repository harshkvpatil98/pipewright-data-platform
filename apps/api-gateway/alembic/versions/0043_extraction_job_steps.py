"""extraction_jobs.steps_json: shape at the source

Phase 12's pushdown planner was advisory: the Studio said what a source
*would* run and every run read a materialised file. An extraction job can now
carry transformation steps. At run time they compile to the IR, the planner
splits them against the connection's surface, the pushable prefix is executed
by the source as SQL wrapped around the job's own query, and the rest runs
here before the dataset is written. Schema only; jobs without steps behave
exactly as before.

Revision ID: 0043_extraction_job_steps
Revises: 0042_report_delivery_channels
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0043_extraction_job_steps'
down_revision = '0042_report_delivery_channels'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('extraction_jobs', sa.Column('steps_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('extraction_jobs', 'steps_json')
