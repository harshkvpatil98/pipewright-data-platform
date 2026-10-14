"""a project's activity: indexes newest first, and what a deletion removed

Adoption-readiness A8 (Y6): the activity stream reads finished runs,
workflow runs, comments and incident events by project, newest first. Each
gets an index on project and time, so a page stays one short read however
long the project's history. The audit log keeps the name of what a deletion
removed, read before it went, so "deleted a dataset" can say which.

Revision ID: 0059_activity
Revises: 0058_metric_alerts
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0059_activity'
down_revision = '0058_metric_alerts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_pipeline_runs_project_completed', 'pipeline_runs', ['project_id', 'completed_at'])
    op.create_index('ix_workflow_runs_project_finished', 'workflow_runs', ['project_id', 'finished_at'])
    op.create_index('ix_comments_project_created', 'comments', ['project_id', 'created_at'])
    op.create_index('ix_incident_events_project_created', 'incident_events', ['project_id', 'created_at'])
    op.add_column('audit_entries', sa.Column('object_name', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_entries', 'object_name')
    op.drop_index('ix_incident_events_project_created', table_name='incident_events')
    op.drop_index('ix_comments_project_created', table_name='comments')
    op.drop_index('ix_workflow_runs_project_finished', table_name='workflow_runs')
    op.drop_index('ix_pipeline_runs_project_completed', table_name='pipeline_runs')
