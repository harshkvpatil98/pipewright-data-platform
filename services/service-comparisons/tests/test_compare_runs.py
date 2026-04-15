from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from service_comparisons.compare_runs import build_run_comparison_summary


def test_transformation_run_full_summary() -> None:
    rid = uuid.uuid4()
    base_id = uuid.uuid4()
    derived_id = uuid.uuid4()
    run = SimpleNamespace(
        id=rid,
        run_type="dataset_transformation",
        status="succeeded",
        summary_json={
            "transformation_type": "dataset_transformation",
            "pipeline_id": str(uuid.uuid4()),
            "base_dataset": {"id": str(base_id), "name": "Base"},
            "derived_dataset": {"id": str(derived_id), "name": "Derived"},
            "row_count_before": 100,
            "row_count_after": 95,
            "column_count_before": 4,
            "column_count_after": 4,
            "step_count": 2,
        },
    )
    out = build_run_comparison_summary(run=run)
    assert out.summary_available is True
    assert out.base_dataset is not None and out.base_dataset.id == base_id
    assert out.derived_dataset is not None and out.derived_dataset.id == derived_id
    assert out.row_count_before == 100 and out.row_count_after == 95
    assert out.step_count == 2
    assert any("fewer rows" in n.lower() for n in out.comparison_notes)


def test_transformation_run_partial_summary_notes() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        run_type="dataset_transformation",
        status="failed",
        summary_json={
            "transformation_type": "dataset_transformation",
            "base_dataset": {"id": str(uuid.uuid4()), "name": "Base"},
            "error": "x",
        },
    )
    out = build_run_comparison_summary(run=run)
    assert out.summary_available is False
    assert any("full before/after" in n.lower() for n in out.comparison_notes)
    assert any("successfully" in n.lower() for n in out.comparison_notes)


def test_ingestion_run_graceful() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        run_type="dataset_ingestion",
        status="succeeded",
        summary_json={
            "ingestion_type": "dataset_upload",
            "dataset": {"id": str(uuid.uuid4()), "name": "D", "row_count": 10, "column_count": 3},
        },
    )
    out = build_run_comparison_summary(run=run)
    assert out.summary_available is False
    assert any("ingestion" in n.lower() for n in out.comparison_notes)
