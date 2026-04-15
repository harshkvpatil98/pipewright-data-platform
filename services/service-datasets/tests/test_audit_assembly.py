from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from service_datasets.audit import build_dataset_audit_summary, safe_artifact_path


def _ds(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "name": "Sales",
        "is_derived": False,
        "parent_dataset_id": None,
        "uploaded_by_user_id": uuid.uuid4(),
        "file_name": "stored.csv",
        "original_filename": "orig.csv",
        "file_type": "csv",
        "file_size_bytes": 100,
        "file_path": "project-1/datasets/x/file.csv",
        "row_count": 10,
        "column_count": 3,
        "ingestion_status": "succeeded",
        "schema_json": {"columns": [{"name": "a"}], "ordered_columns": ["a", "b"]},
        "profile_json": None,
        "ingestion_error": None,
        "last_profiled_at": None,
        "created_from_pipeline_id": None,
        "pipeline_run_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_safe_artifact_path_hides_absolute() -> None:
    assert safe_artifact_path("/etc/passwd") is None
    assert safe_artifact_path("datasets/out.csv") == "datasets/out.csv"


def test_build_dataset_audit_summary_without_profile_notes() -> None:
    pid = uuid.uuid4()
    dataset = _ds(profile_json=None)
    summary = build_dataset_audit_summary(dataset=dataset, project_id=pid, project_name="P1")
    assert summary.metrics.row_count == 10
    assert "Dataset profile has not been generated." in summary.warnings
    assert summary.profile_highlights.duplicate_row_count is None


def test_build_dataset_audit_summary_with_profile_quality() -> None:
    pid = uuid.uuid4()
    profile = {
        "duplicate_row_count": 2,
        "duplicate_row_percentage": 5.0,
        "completeness_score": 99.0,
        "quality_flags": {
            "high_null_columns": ["x"],
            "constant_value_columns": [],
            "potential_id_columns": ["id"],
        },
    }
    dataset = _ds(profile_json=profile)
    summary = build_dataset_audit_summary(dataset=dataset, project_id=pid, project_name="P1")
    assert summary.profile_highlights.duplicate_row_count == 2
    assert "duplicate rows" in " ".join(summary.warnings).lower()
    assert summary.profile_highlights.high_null_columns == ["x"]


def test_build_dataset_audit_summary_derived_lineage() -> None:
    pid = uuid.uuid4()
    parent = uuid.uuid4()
    pipe = uuid.uuid4()
    run = uuid.uuid4()
    dataset = _ds(
        is_derived=True,
        parent_dataset_id=parent,
        created_from_pipeline_id=pipe,
        pipeline_run_id=run,
        profile_json={"duplicate_row_count": 0, "quality_flags": {"high_null_columns": []}},
    )
    summary = build_dataset_audit_summary(dataset=dataset, project_id=pid, project_name="P1")
    assert summary.is_derived is True
    assert str(pipe) in " ".join(summary.warnings)
    assert summary.lineage.parent_dataset_id == parent
