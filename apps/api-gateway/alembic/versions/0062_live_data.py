"""live data: sources that keep up, tables kept current, live recipes

Roadmap Phase 20 (D1): how often a live source is read and saved, its
position as JSON, failures and a lease so one runner reads it at a time;
an event's position unique within its source; each followed table kept as
it is now; live recipes, their state and their windows' results.

Revision ID: 0062_live_data
Revises: 0061_working_together
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = '0062_live_data'
down_revision = '0061_working_together'
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    with op.batch_alter_table('stream_sources') as batch:
        batch.add_column(sa.Column('read_every_seconds', sa.Integer(), server_default='5', nullable=False))
        batch.add_column(sa.Column('save_every_seconds', sa.Integer(), server_default='60', nullable=False))
        batch.add_column(sa.Column('keep_events_hours', sa.Integer(), server_default='168', nullable=False))
        batch.add_column(sa.Column('next_read_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('failures', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('failure_notified_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('log_saved_seq', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('behind', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('last_read_count', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('claim_owner_id', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_index('ix_stream_sources_due', ['status', 'next_read_at'])

    # Existing sources: the log dataset already holds every event (it was
    # rewritten in full on each save), a change-capture position becomes JSON,
    # and the sequence counter agrees with the events there are.
    conn = op.get_bind()
    sources = sa.table('stream_sources', sa.column('id', sa.Uuid()), sa.column('kind', sa.String()),
                       sa.column('cursor', sa.Text()), sa.column('dataset_id', sa.Uuid()),
                       sa.column('events_count', sa.Integer()), sa.column('log_saved_seq', sa.Integer()))
    events = sa.table('stream_events', sa.column('source_id', sa.Uuid()), sa.column('seq', sa.Integer()))
    for row in conn.execute(sa.select(sources.c.id, sources.c.kind, sources.c.cursor, sources.c.dataset_id)).all():
        top = conn.execute(sa.select(sa.func.coalesce(sa.func.max(events.c.seq), 0)).where(events.c.source_id == row.id)).scalar()
        values: dict[str, object] = {'events_count': int(top or 0)}
        if row.dataset_id is not None:
            values['log_saved_seq'] = int(top or 0)
        if row.kind == 'postgres_cdc' and row.cursor and not row.cursor.startswith('{'):
            values['cursor'] = json.dumps({'lsn': row.cursor})
        conn.execute(sources.update().where(sources.c.id == row.id).values(**values))

    with op.batch_alter_table('stream_events') as batch:
        batch.drop_index('ix_stream_events_position')
        batch.create_unique_constraint('uq_stream_events_source_position', ['source_id', 'position'])
        batch.create_index('ix_stream_events_received', ['source_id', 'received_at'])

    op.create_table(
        'stream_tables',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('table_name', sa.String(length=320), nullable=False),
        sa.Column('key_columns_json', sa.JSON(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=True),
        sa.Column('state', sa.String(length=24), server_default='waiting', nullable=False),
        sa.Column('snapshot_rows', sa.Integer(), nullable=True),
        sa.Column('rows_now', sa.Integer(), nullable=True),
        sa.Column('applied_seq', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_saved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['source_id'], ['stream_sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'table_name', name='uq_stream_tables_source_table'),
    )

    op.create_table(
        'live_recipes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('recipe_id', sa.Uuid(), nullable=True),
        sa.Column('lookup_json', sa.JSON(), nullable=True),
        sa.Column('window_json', sa.JSON(), nullable=True),
        sa.Column('group_by_json', sa.JSON(), nullable=False),
        sa.Column('measures_json', sa.JSON(), nullable=False),
        sa.Column('output_dataset_id', sa.Uuid(), nullable=True),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('processed_seq', sa.Integer(), server_default='0', nullable=False),
        sa.Column('saved_seq', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=24), server_default='active', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('late_dropped', sa.Integer(), server_default='0', nullable=False),
        sa.Column('late_restated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('without_time', sa.Integer(), server_default='0', nullable=False),
        sa.Column('unmatched', sa.Integer(), server_default='0', nullable=False),
        sa.Column('events_in', sa.Integer(), server_default='0', nullable=False),
        sa.Column('results_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_saved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['stream_sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipe_id'], ['transformation_pipelines.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['output_dataset_id'], ['datasets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_live_recipes_source', 'live_recipes', ['source_id'])

    op.create_table(
        'live_recipe_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('live_recipe_id', sa.Uuid(), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('group_key', sa.String(length=64), nullable=False),
        sa.Column('group_json', sa.JSON(), nullable=False),
        sa.Column('values_json', sa.JSON(), nullable=False),
        sa.Column('events', sa.Integer(), nullable=False),
        sa.Column('final', sa.Boolean(), nullable=False),
        sa.Column('restated', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['live_recipe_id'], ['live_recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('live_recipe_id', 'window_start', 'window_end', 'group_key',
                            name='uq_live_recipe_results_window'),
    )
    op.create_index('ix_live_recipe_results_end', 'live_recipe_results', ['live_recipe_id', 'window_end'])


def downgrade() -> None:
    op.drop_index('ix_live_recipe_results_end', table_name='live_recipe_results')
    op.drop_table('live_recipe_results')
    op.drop_index('ix_live_recipes_source', table_name='live_recipes')
    op.drop_table('live_recipes')
    op.drop_table('stream_tables')
    with op.batch_alter_table('stream_events') as batch:
        batch.drop_index('ix_stream_events_received')
        batch.drop_constraint('uq_stream_events_source_position', type_='unique')
        batch.create_index('ix_stream_events_position', ['source_id', 'position'])
    with op.batch_alter_table('stream_sources') as batch:
        batch.drop_index('ix_stream_sources_due')
        for column in ('claim_expires_at', 'claim_owner_id', 'last_read_count', 'behind', 'log_saved_seq',
                       'failure_notified_at', 'failures', 'next_read_at', 'keep_events_hours',
                       'save_every_seconds', 'read_every_seconds'):
            batch.drop_column(column)
