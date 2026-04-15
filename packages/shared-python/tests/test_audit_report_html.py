from __future__ import annotations

import uuid

from shared_python.reporting.audit_report_html import (
    render_dataset_audit_report_html,
    render_run_audit_report_html,
    sanitize_audit_filename_component,
)


def test_sanitize_filename_strips_unsafe() -> None:
    assert sanitize_audit_filename_component("My / Dataset !!") == "My-Dataset"
    assert sanitize_audit_filename_component("   ", fallback="x") == "x"


def test_dataset_html_contains_core_sections() -> None:
    pid = uuid.uuid4()
    did = uuid.uuid4()
    html = render_dataset_audit_report_html(
        {
            "id": str(did),
            "name": "Orders",
            "is_derived": False,
            "parent_dataset_id": None,
            "project": {"id": str(pid), "name": "Demo"},
            "ownership": {"uploaded_by_user_id": None},
            "artifact": {
                "file_name": "a.csv",
                "original_filename": "a.csv",
                "file_type": "csv",
                "file_size_bytes": 10,
                "file_path": "p/d/x.csv",
            },
            "metrics": {
                "row_count": 1,
                "column_count": 2,
                "ingestion_status": "succeeded",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "last_profiled_at": None,
            },
            "profile_highlights": {
                "duplicate_row_count": 0,
                "duplicate_row_percentage": 0.0,
                "completeness_score": 100.0,
                "high_null_columns": [],
                "constant_value_columns": [],
                "potential_id_columns": [],
            },
            "lineage": {
                "created_from_pipeline_id": None,
                "pipeline_run_id": None,
                "parent_dataset_id": None,
            },
            "schema_summary": {"column_count": 2, "sample_column_names": ["a", "b"]},
            "warnings": ["Dataset ingestion completed successfully."],
        }
    )
    assert "Dataset audit report" in html
    assert "Orders" in html
    assert "Dataset ingestion completed successfully." in html
    assert "<style>" in html


def test_run_html_contains_summary_and_logs() -> None:
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    html = render_run_audit_report_html(
        {
            "id": str(rid),
            "run_type": "sample_orchestration",
            "status": "succeeded",
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "completed_at": "2026-01-01T00:00:02Z",
            "project_id": str(pid),
            "triggered_by_user_id": str(uuid.uuid4()),
            "pipeline_id": None,
            "related_dataset_ids": [],
            "summary_json": {"project_slug": "demo"},
            "logs_json": {"events": [{"stage": "succeeded", "message": "done"}]},
            "highlights": {
                "stage_count": 1,
                "failed_stage": None,
                "derived_dataset_created": False,
                "ingestion_type": None,
                "transformation_type": None,
            },
            "warnings": ["Run completed successfully."],
        }
    )
    assert "Pipeline run audit report" in html
    assert "project_slug" in html
    assert "succeeded" in html
