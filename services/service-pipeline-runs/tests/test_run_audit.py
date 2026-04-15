from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from service_pipeline_runs.audit import (
    build_run_audit_summary,
    extract_related_dataset_ids,
)


def test_extract_related_dataset_ids_orders_unique() -> None:
    d1 = str(uuid.uuid4())
    d2 = str(uuid.uuid4())
    summary = {
        "dataset": {"id": d1},
        "base_dataset": {"id": d2},
        "derived_dataset": {"id": d1},
    }
    ids = extract_related_dataset_ids(summary)
    assert len(ids) == 2


def test_build_run_audit_summary_ingestion_success() -> None:
    ds = uuid.uuid4()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={
            "ingestion_type": "dataset_upload",
            "dataset": {"id": str(ds), "name": "A", "ingestion_status": "succeeded"},
        },
        logs_json={"events": [{"stage": "parse", "message": "ok"}, {"stage": "succeeded", "message": "done"}]},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.status == "succeeded"
    assert audit.highlights.stage_count == 2
    assert ds in audit.related_dataset_ids
    assert any("completed successfully" in w for w in audit.warnings)
    assert "Run summary metadata is incomplete." not in audit.warnings


def test_build_run_audit_summary_partial_logs_and_empty_summary() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="failed",
        started_at=None,
        completed_at=datetime.now(UTC),
        summary_json={},
        logs_json={"unexpected": True},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.stage_count == 0
    assert "Run summary metadata is incomplete." in audit.warnings


def test_build_run_audit_summary_transformation_derived() -> None:
    base = uuid.uuid4()
    derived = uuid.uuid4()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        run_type="dataset_transformation",
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={
            "transformation_type": "dataset_transformation",
            "base_dataset": {"id": str(base), "name": "B"},
            "derived_dataset": {"id": str(derived), "name": "C"},
        },
        logs_json={"events": [{"stage": "succeeded", "message": "Transformation run completed successfully."}]},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.derived_dataset_created is True
    assert derived in audit.related_dataset_ids
    assert any("derived dataset" in w.lower() for w in audit.warnings)


def test_build_run_audit_summary_failed_stage_from_summary() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={"failure_stage": "parse", "ingestion_type": "dataset_upload"},
        logs_json={"events": []},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.failed_stage == "parse"
    assert any("parse" in w.lower() for w in audit.warnings)
