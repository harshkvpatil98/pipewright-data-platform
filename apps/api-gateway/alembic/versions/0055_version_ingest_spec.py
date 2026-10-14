"""each dataset version records how its file is read

Adoption-readiness A8: reading a dataset back (a chart, a check, a download,
a delivery) ignored the settings confirmed at import, so a file whose dates
were ambiguous imported and then could not be read again. Readers now use
the settings, which belong to each stored file: the version that holds it.

Backfill: a dataset's settings move to its head version when that version
came from an import; when the head came from elsewhere (a recipe's output),
the dataset's settings were an earlier upload's and are cleared.

Revision ID: 0055_version_ingest_spec
Revises: 0054_task_settings_hash
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0055_version_ingest_spec'
down_revision = '0054_task_settings_hash'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dataset_versions', sa.Column('ingest_spec_json', sa.JSON(), nullable=True))

    bind = op.get_bind()
    datasets = sa.table(
        'datasets', sa.column('id', sa.Uuid), sa.column('file_path', sa.Text), sa.column('ingest_spec_json', sa.JSON),
    )
    versions = sa.table(
        'dataset_versions', sa.column('id', sa.Uuid), sa.column('dataset_id', sa.Uuid),
        sa.column('file_path', sa.Text), sa.column('version_number', sa.Integer),
        sa.column('pipeline_run_id', sa.Uuid), sa.column('ingest_spec_json', sa.JSON),
    )
    runs = sa.table('pipeline_runs', sa.column('id', sa.Uuid), sa.column('run_type', sa.String))
    for dataset in bind.execute(
        sa.select(datasets.c.id, datasets.c.file_path, datasets.c.ingest_spec_json).where(
            datasets.c.ingest_spec_json.is_not(None)
        )
    ).all():
        head = bind.execute(
            sa.select(versions.c.id, runs.c.run_type)
            .select_from(versions.outerjoin(runs, runs.c.id == versions.c.pipeline_run_id))
            .where(versions.c.dataset_id == dataset.id, versions.c.file_path == dataset.file_path)
            .order_by(versions.c.version_number.desc())
            .limit(1)
        ).first()
        if head is not None and head.run_type == 'dataset_ingestion':
            bind.execute(
                versions.update().where(versions.c.id == head.id).values(ingest_spec_json=dataset.ingest_spec_json)
            )
        else:
            bind.execute(datasets.update().where(datasets.c.id == dataset.id).values(ingest_spec_json=None))


def downgrade() -> None:
    op.drop_column('dataset_versions', 'ingest_spec_json')
