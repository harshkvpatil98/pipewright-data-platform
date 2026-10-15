"""data contracts: promises about a dataset that new data must keep

Roadmap Phase 19, second half (C1): a contract per dataset with its
versions, the people following it, the problems new data caused, and the
messages the worker sends about them.

Revision ID: 0060_data_contracts
Revises: 0059_activity
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0060_data_contracts'
down_revision = '0059_activity'
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'data_contracts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enforcement', sa.String(length=16), nullable=False),
        sa.Column('terms_json', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', name='uq_data_contracts_dataset'),
    )
    op.create_index('ix_data_contracts_project_id', 'data_contracts', ['project_id'])

    op.create_table(
        'data_contract_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enforcement', sa.String(length=16), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('terms_json', sa.JSON(), nullable=False),
        sa.Column('changes_json', sa.JSON(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['contract_id'], ['data_contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contract_id', 'version', name='uq_data_contract_versions_number'),
    )

    op.create_table(
        'data_contract_followers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(['contract_id'], ['data_contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contract_id', 'user_id', name='uq_data_contract_followers_person'),
    )

    op.create_table(
        'data_contract_problems',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('contract_version', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('outcome', sa.String(length=16), nullable=False),
        sa.Column('source_type', sa.String(length=16), nullable=True),
        sa.Column('source_id', sa.Uuid(), nullable=True),
        sa.Column('source_name', sa.String(length=200), nullable=True),
        sa.Column('reasons_json', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('times_seen', sa.Integer(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('pipeline_run_id', sa.Uuid(), nullable=True),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['data_contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_data_contract_problems_contract_open', 'data_contract_problems', ['contract_id', 'resolved_at']
    )
    op.create_index(
        'ix_data_contract_problems_project_created', 'data_contract_problems', ['project_id', 'created_at']
    )

    op.create_table(
        'data_contract_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('dataset_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=240), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['data_contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_data_contract_events_unsent', 'data_contract_events', ['sent_at'])


def downgrade() -> None:
    op.drop_index('ix_data_contract_events_unsent', table_name='data_contract_events')
    op.drop_table('data_contract_events')
    op.drop_index('ix_data_contract_problems_project_created', table_name='data_contract_problems')
    op.drop_index('ix_data_contract_problems_contract_open', table_name='data_contract_problems')
    op.drop_table('data_contract_problems')
    op.drop_table('data_contract_followers')
    op.drop_table('data_contract_versions')
    op.drop_index('ix_data_contracts_project_id', table_name='data_contracts')
    op.drop_table('data_contracts')
