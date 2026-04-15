from __future__ import annotations

import uuid
from typing import Any

from service_datasets.models import Dataset

from service_comparisons.schemas import (
    ComparisonDatasetSide,
    DatasetComparisonSummary,
    LineageComparisonContext,
    ProfileComparisonDelta,
    SchemaComparisonDelta,
    SchemaTypeChange,
)


def _column_type_map(schema_json: dict[str, Any] | None) -> dict[str, str]:
    if not schema_json or not isinstance(schema_json.get("columns"), list):
        return {}
    out: dict[str, str] = {}
    for col in schema_json["columns"]:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if name is None:
            continue
        out[str(name)] = str(col.get("inferred_type", "") or "")
    return out


def _dup_count(profile: dict[str, Any] | None) -> int | None:
    if not profile:
        return None
    raw = profile.get("duplicate_row_count")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _completeness(profile: dict[str, Any] | None) -> float | None:
    if not profile:
        return None
    raw = profile.get("completeness_score")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _side(ds: Dataset) -> ComparisonDatasetSide:
    return ComparisonDatasetSide(
        id=ds.id,
        name=ds.name,
        is_derived=ds.is_derived,
        row_count=ds.row_count,
        column_count=ds.column_count,
    )


def build_dataset_comparison_summary(*, left: Dataset, right: Dataset) -> DatasetComparisonSummary:
    left_map = _column_type_map(left.schema_json)
    right_map = _column_type_map(right.schema_json)
    left_names = set(left_map.keys())
    right_names = set(right_map.keys())

    added = sorted(right_names - left_names)
    removed = sorted(left_names - right_names)
    changed: list[SchemaTypeChange] = []
    for name in sorted(left_names & right_names):
        bt, at = left_map[name], right_map[name]
        if bt != at:
            changed.append(SchemaTypeChange(column_name=name, before_type=bt, after_type=at))

    lp, rp = left.profile_json, right.profile_json
    profile_delta = ProfileComparisonDelta(
        duplicate_row_count_before=_dup_count(lp if isinstance(lp, dict) else None),
        duplicate_row_count_after=_dup_count(rp if isinstance(rp, dict) else None),
        completeness_score_before=_completeness(lp if isinstance(lp, dict) else None),
        completeness_score_after=_completeness(rp if isinstance(rp, dict) else None),
    )

    row_delta = (
        None
        if left.row_count is None or right.row_count is None
        else int(right.row_count) - int(left.row_count)
    )
    col_delta = (
        None
        if left.column_count is None or right.column_count is None
        else int(right.column_count) - int(left.column_count)
    )

    related_pc = (right.parent_dataset_id == left.id) or (left.parent_dataset_id == right.id)
    parent_id: uuid.UUID | None = None
    pipeline_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    if right.parent_dataset_id == left.id:
        parent_id = left.id
        pipeline_id = right.created_from_pipeline_id
        run_id = right.pipeline_run_id
    elif left.parent_dataset_id == right.id:
        parent_id = right.id
        pipeline_id = left.created_from_pipeline_id
        run_id = left.pipeline_run_id

    lineage = LineageComparisonContext(
        related_by_parent_child=related_pc,
        parent_dataset_id=parent_id,
        created_from_pipeline_id=pipeline_id,
        related_run_id=run_id,
    )

    notes = _dataset_comparison_notes(
        left=left,
        right=right,
        row_delta=row_delta,
        col_delta=col_delta,
        profile_delta=profile_delta,
        added=added,
        removed=removed,
        changed=changed,
    )

    return DatasetComparisonSummary(
        left_dataset=_side(left),
        right_dataset=_side(right),
        row_count_delta=row_delta,
        column_count_delta=col_delta,
        profile_delta=profile_delta,
        schema_delta=SchemaComparisonDelta(
            added_columns=added,
            removed_columns=removed,
            changed_type_columns=changed,
        ),
        lineage_context=lineage,
        comparison_notes=notes,
    )


def _dataset_comparison_notes(
    *,
    left: Dataset,
    right: Dataset,
    row_delta: int | None,
    col_delta: int | None,
    profile_delta: ProfileComparisonDelta,
    added: list[str],
    removed: list[str],
    changed: list[SchemaTypeChange],
) -> list[str]:
    notes: list[str] = []

    if row_delta is not None:
        if row_delta < 0:
            notes.append("Right dataset has fewer rows than the left dataset.")
        elif row_delta > 0:
            notes.append("Right dataset has more rows than the left dataset.")
        else:
            notes.append("Row counts match between the two datasets.")

    if col_delta is not None:
        if col_delta < 0:
            notes.append("Right dataset has fewer columns than the left dataset.")
        elif col_delta > 0:
            notes.append("Right dataset has more columns than the left dataset.")
        else:
            notes.append("Column counts match between the two datasets.")

    if added:
        notes.append("New columns were introduced on the right dataset relative to the left.")
    if removed:
        notes.append("Some columns present on the left are absent on the right.")
    if changed:
        notes.append("One or more columns changed inferred type between the two datasets.")

    db, da = profile_delta.duplicate_row_count_before, profile_delta.duplicate_row_count_after
    if db is not None and da is not None:
        if da < db:
            notes.append("Duplicate rows were reduced on the right dataset relative to the left.")
        elif da > db:
            notes.append("Duplicate row count is higher on the right dataset than on the left.")

    cb, ca = profile_delta.completeness_score_before, profile_delta.completeness_score_after
    if cb is not None and ca is not None:
        if ca > cb:
            notes.append("Completeness score improved on the right dataset.")
        elif ca < cb:
            notes.append("Completeness score is lower on the right dataset than on the left.")

    if left.profile_json is None or right.profile_json is None:
        notes.append("Profile metadata is missing for one or both datasets; some deltas may be unavailable.")

    if right.is_derived and not left.is_derived:
        notes.append("Right dataset is marked as derived while the left is not.")
    elif left.is_derived and right.is_derived:
        notes.append("Both datasets are marked as derived; confirm lineage when interpreting changes.")

    # Deterministic de-dupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered
