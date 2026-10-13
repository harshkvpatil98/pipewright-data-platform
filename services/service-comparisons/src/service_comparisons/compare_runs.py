from __future__ import annotations

import uuid
from typing import Any

from service_pipeline_runs.models import PipelineRun

from service_comparisons.schemas import RunComparisonDatasetRef, RunComparisonSummary


def _uuid_from(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _dataset_ref(block: Any) -> RunComparisonDatasetRef | None:
    if not isinstance(block, dict):
        return None
    raw_id = block.get("id")
    uid = _uuid_from(raw_id)
    if uid is None:
        return None
    name = block.get("name")
    return RunComparisonDatasetRef(id=uid, name=str(name) if name is not None else "")


def build_run_comparison_summary(*, run: PipelineRun) -> RunComparisonSummary:
    summary = run.summary_json
    raw_summary_present = isinstance(summary, dict) and len(summary) > 0
    if not isinstance(summary, dict):
        summary = {}

    notes: list[str] = []
    base = _dataset_ref(summary.get("base_dataset"))
    derived = _dataset_ref(summary.get("derived_dataset"))

    row_b = summary.get("row_count_before")
    row_a = summary.get("row_count_after")
    col_b = summary.get("column_count_before")
    col_a = summary.get("column_count_after")
    step_count = summary.get("step_count")

    def _int_or_none(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    row_b = _int_or_none(row_b)
    row_a = _int_or_none(row_a)
    col_b = _int_or_none(col_b)
    col_a = _int_or_none(col_a)
    step_n = _int_or_none(step_count)

    transformation = summary.get("transformation_type") == "dataset_transformation"
    ingestion = summary.get("ingestion_type") == "dataset_upload"

    summary_available = transformation and (
        row_b is not None and row_a is not None and col_b is not None and col_a is not None
    )

    if not transformation and not ingestion and raw_summary_present:
        notes.append(
            "Before and after counts are kept for recipe runs; this run is a different kind."
        )

    if ingestion:
        notes.append(
            "This run uploaded a file. To compare two datasets, open one and choose Compare."
        )
        ds = summary.get("dataset")
        if isinstance(ds, dict) and row_a is None:
            row_a = _int_or_none(ds.get("row_count"))
        if isinstance(ds, dict) and col_a is None:
            col_a = _int_or_none(ds.get("column_count"))

    if transformation:
        if not summary_available:
            notes.append("This run did not record full before and after counts.")
        if base and derived:
            if row_b is not None and row_a is not None:
                if row_a < row_b:
                    notes.append("The result has fewer rows than the input.")
                elif row_a > row_b:
                    notes.append("The result has more rows than the input.")
            if col_b is not None and col_a is not None and col_a != col_b:
                notes.append("The number of columns changed.")
        elif transformation and base and not derived:
            notes.append("It recorded its input but not its result.")

    if run.status == "failed":
        notes.append("The run failed, so these counts may be incomplete.")

    if not raw_summary_present:
        notes.append("Nothing was recorded about this run's data.")

    # Dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    pipeline_id = _uuid_from(summary.get("pipeline_id"))
    if pipeline_id is None and isinstance(summary.get("pipeline"), dict):
        pipeline_id = _uuid_from(summary["pipeline"].get("id"))

    return RunComparisonSummary(
        run_id=run.id,
        run_type=run.run_type,
        status=run.status,
        pipeline_id=pipeline_id,
        base_dataset=base,
        derived_dataset=derived,
        row_count_before=row_b,
        row_count_after=row_a,
        column_count_before=col_b,
        column_count_after=col_a,
        step_count=step_n,
        summary_available=summary_available,
        comparison_notes=ordered,
        raw_summary_present=raw_summary_present,
    )
