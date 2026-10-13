"""Reading a stored extraction job back through the API model.

A job with no shaping steps stores NULL in `steps_json` (`create_job` writes
`... or None`). The read model declared `steps` as a list, so every such job
failed validation: creating one returned 500, and listing a project's jobs --
which the Sources page does on every load -- returned 500 for any project that
had one. The browser reported it only as "Failed to fetch".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from service_extraction.schemas import ExtractionJobRead


def _stored_job(**overrides):
    now = datetime.now(UTC)
    row = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        name="Orders",
        description=None,
        source_kind="table",
        source_schema=None,
        source_table="orders",
        query_sql=None,
        load_mode="full_refresh",
        cursor_column=None,
        primary_key_columns=[],
        max_rows=1_000_000,
        steps_json=None,
        watermark_value=None,
        watermark_updated_at=None,
        target_dataset_id=None,
        enabled=True,
        last_run_at=None,
        last_run_status=None,
        last_row_count=None,
        last_error_message=None,
        execution_count=0,
        created_at=now,
        updated_at=now,
    )
    row.update(overrides)
    return SimpleNamespace(**row)


def test_a_job_without_steps_reads_as_an_empty_list() -> None:
    job = ExtractionJobRead.model_validate(_stored_job(), from_attributes=True)
    assert job.steps == []


def test_a_job_with_steps_keeps_them() -> None:
    steps = [{"step_type": "filter_rows", "config": {"conditions": []}}]
    job = ExtractionJobRead.model_validate(_stored_job(steps_json=steps), from_attributes=True)
    assert job.steps == steps
