from __future__ import annotations

import uuid
from types import SimpleNamespace

from service_comparisons.compare_datasets import build_dataset_comparison_summary


def _ds(**kwargs: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "name": "L",
        "is_derived": False,
        "parent_dataset_id": None,
        "created_from_pipeline_id": None,
        "pipeline_run_id": None,
        "row_count": 100,
        "column_count": 5,
        "schema_json": {
            "columns": [
                {"name": "a", "inferred_type": "int"},
                {"name": "b", "inferred_type": "string"},
            ]
        },
        "profile_json": {
            "duplicate_row_count": 2,
            "completeness_score": 90.0,
        },
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_schema_delta_added_removed_changed() -> None:
    left = _ds()
    right = _ds(
        id=uuid.uuid4(),
        name="R",
        row_count=80,
        column_count=6,
        schema_json={
            "columns": [
                {"name": "a", "inferred_type": "float"},
                {"name": "b", "inferred_type": "string"},
                {"name": "c", "inferred_type": "int"},
            ]
        },
        profile_json={"duplicate_row_count": 0, "completeness_score": 95.0},
    )
    out = build_dataset_comparison_summary(left=left, right=right)
    assert out.row_count_delta == -20
    assert "c" in out.schema_delta.added_columns
    assert out.schema_delta.removed_columns == []
    assert any(c.column_name == "a" for c in out.schema_delta.changed_type_columns)
    assert out.profile_delta.duplicate_row_count_before == 2
    assert out.profile_delta.duplicate_row_count_after == 0


def test_lineage_parent_child() -> None:
    pid = uuid.uuid4()
    left = _ds(id=pid, name="Base")
    right = _ds(
        id=uuid.uuid4(),
        is_derived=True,
        parent_dataset_id=pid,
        created_from_pipeline_id=uuid.uuid4(),
        pipeline_run_id=uuid.uuid4(),
    )
    out = build_dataset_comparison_summary(left=left, right=right)
    assert out.lineage_context.related_by_parent_child is True
    assert out.lineage_context.parent_dataset_id == pid


def test_comparison_notes_duplicate_and_completeness() -> None:
    left = _ds(profile_json={"duplicate_row_count": 10, "completeness_score": 80.0})
    right = _ds(
        id=uuid.uuid4(),
        profile_json={"duplicate_row_count": 2, "completeness_score": 92.0},
    )
    out = build_dataset_comparison_summary(left=left, right=right)
    text = " ".join(out.comparison_notes).lower()
    assert "duplicate" in text
    assert "completeness" in text
