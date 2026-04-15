from __future__ import annotations

import os
import uuid
from typing import Any

from service_datasets.models import Dataset
from service_datasets.schemas import (
    DatasetAuditArtifact,
    DatasetAuditLineage,
    DatasetAuditMetrics,
    DatasetAuditOwnership,
    DatasetAuditProfileHighlights,
    DatasetAuditProject,
    DatasetAuditSchemaSummary,
    DatasetAuditSummary,
)


def safe_artifact_path(file_path: str | None) -> str | None:
    """Return a relative storage path for display, or None if unsafe (absolute or traversal)."""
    if file_path is None:
        return None
    p = str(file_path).strip()
    if not p:
        return None
    normalized = p.replace("\\", "/")
    if os.path.isabs(p) or normalized.startswith("//"):
        return None
    if ".." in normalized.split("/"):
        return None
    return p


def _profile_quality_flags(profile: dict[str, Any] | None) -> dict[str, list[str]]:
    if not profile:
        return {
            "high_null_columns": [],
            "constant_value_columns": [],
            "potential_id_columns": [],
        }
    qf = profile.get("quality_flags")
    if isinstance(qf, dict):
        return {
            "high_null_columns": list(qf.get("high_null_columns") or []),
            "constant_value_columns": list(qf.get("constant_value_columns") or []),
            "potential_id_columns": list(qf.get("potential_id_columns") or []),
        }
    return {
        "high_null_columns": [],
        "constant_value_columns": [],
        "potential_id_columns": [],
    }


def _build_dataset_audit_notes(dataset: Dataset, profile: dict[str, Any] | None) -> list[str]:
    notes: list[str] = []

    if dataset.ingestion_status == "succeeded":
        notes.append("Dataset ingestion completed successfully.")
    elif dataset.ingestion_status == "failed":
        notes.append("Dataset ingestion did not complete successfully.")
    elif dataset.ingestion_status in {"pending", "queued", "running"}:
        notes.append("Dataset ingestion is not finished yet.")

    if dataset.is_derived:
        notes.append("Dataset is derived from another dataset.")
    if dataset.created_from_pipeline_id:
        notes.append(f"Dataset was created by transformation pipeline {dataset.created_from_pipeline_id}.")

    if profile is None:
        notes.append("Dataset profile has not been generated.")
    else:
        dup = int(profile.get("duplicate_row_count") or 0)
        if dup > 0:
            notes.append("Dataset has duplicate rows according to latest profile.")
        qf = _profile_quality_flags(profile)
        if qf["high_null_columns"]:
            notes.append("One or more columns have high null percentages.")

    if dataset.ingestion_error:
        notes.append("Dataset has a recorded ingestion error message.")

    # De-duplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def build_dataset_audit_summary(
    *,
    dataset: Dataset,
    project_id: uuid.UUID,
    project_name: str,
) -> DatasetAuditSummary:
    profile = dataset.profile_json
    qf = _profile_quality_flags(profile)

    dup_count: int | None = None
    dup_pct: float | None = None
    completeness: float | None = None
    if profile:
        dup_count = profile.get("duplicate_row_count")
        if dup_count is not None:
            dup_count = int(dup_count)
        dup_pct = profile.get("duplicate_row_percentage")
        if isinstance(dup_pct, (int, float)):
            dup_pct = float(dup_pct)
        else:
            dup_pct = None
        comp = profile.get("completeness_score")
        if isinstance(comp, (int, float)):
            completeness = float(comp)
        else:
            completeness = None

    schema_json = dataset.schema_json or {}
    columns = schema_json.get("columns") if isinstance(schema_json, dict) else None
    col_count = len(columns) if isinstance(columns, list) else dataset.column_count
    ordered = schema_json.get("ordered_columns") if isinstance(schema_json, dict) else None
    sample_names: list[str] = []
    if isinstance(ordered, list):
        sample_names = [str(x) for x in ordered[:8]]
    elif isinstance(columns, list):
        for c in columns[:8]:
            if isinstance(c, dict) and c.get("name") is not None:
                sample_names.append(str(c["name"]))

    schema_summary = DatasetAuditSchemaSummary(
        column_count=col_count,
        sample_column_names=sample_names,
    )

    lineage = DatasetAuditLineage(
        created_from_pipeline_id=dataset.created_from_pipeline_id,
        pipeline_run_id=dataset.pipeline_run_id,
        parent_dataset_id=dataset.parent_dataset_id,
    )

    warnings = _build_dataset_audit_notes(dataset, profile)

    return DatasetAuditSummary(
        id=dataset.id,
        name=dataset.name,
        is_derived=dataset.is_derived,
        parent_dataset_id=dataset.parent_dataset_id,
        project=DatasetAuditProject(id=project_id, name=project_name),
        ownership=DatasetAuditOwnership(uploaded_by_user_id=dataset.uploaded_by_user_id),
        artifact=DatasetAuditArtifact(
            file_name=dataset.file_name,
            original_filename=dataset.original_filename,
            file_type=dataset.file_type,
            file_size_bytes=dataset.file_size_bytes,
            file_path=safe_artifact_path(dataset.file_path),
        ),
        metrics=DatasetAuditMetrics(
            row_count=dataset.row_count,
            column_count=dataset.column_count,
            ingestion_status=dataset.ingestion_status,
            created_at=dataset.created_at,
            updated_at=dataset.updated_at,
            last_profiled_at=dataset.last_profiled_at,
        ),
        profile_highlights=DatasetAuditProfileHighlights(
            duplicate_row_count=dup_count,
            duplicate_row_percentage=dup_pct,
            completeness_score=completeness,
            high_null_columns=list(qf["high_null_columns"]),
            constant_value_columns=list(qf["constant_value_columns"]),
            potential_id_columns=list(qf["potential_id_columns"]),
        ),
        lineage=lineage,
        schema_summary=schema_summary,
        warnings=warnings,
    )
