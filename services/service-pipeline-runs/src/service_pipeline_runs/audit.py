from __future__ import annotations

import uuid
from typing import Any

from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.schemas import RunAuditHighlights, RunAuditSummary


def extract_related_dataset_ids(summary: dict[str, Any] | None) -> list[uuid.UUID]:
    if not summary:
        return []
    keys = ("dataset", "base_dataset", "derived_dataset")
    found: list[uuid.UUID] = []
    for key in keys:
        block = summary.get(key)
        if not isinstance(block, dict):
            continue
        raw_id = block.get("id")
        if raw_id is None:
            continue
        try:
            found.append(uuid.UUID(str(raw_id)))
        except ValueError:
            continue
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _log_events(logs_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not logs_json:
        return []
    events = logs_json.get("events")
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict)]


def _infer_failed_stage(summary: dict[str, Any] | None, events: list[dict[str, Any]]) -> str | None:
    if summary and summary.get("failure_stage"):
        return str(summary["failure_stage"])
    for ev in reversed(events):
        if str(ev.get("stage", "")).lower() == "failed":
            details = ev.get("details")
            if isinstance(details, dict) and details.get("failure_stage"):
                return str(details["failure_stage"])
            return str(ev.get("stage") or "failed")
    return None


def _derived_dataset_created(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    if summary.get("transformation_type") == "dataset_transformation":
        dd = summary.get("derived_dataset")
        return isinstance(dd, dict) and bool(dd.get("id"))
    return False


def _ingestion_transformation_labels(summary: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None
    ing = summary.get("ingestion_type")
    if isinstance(ing, str):
        ing_out: str | None = ing
    else:
        ing_out = None
    tr = summary.get("transformation_type")
    if isinstance(tr, str):
        tr_out: str | None = tr
    else:
        tr_out = None
    return ing_out, tr_out


_STAGE_WORDS = {
    "upload": "saving the file",
    "parse": "reading the rows",
    "profile": "working out the columns",
    "materialize_profile": "working out the columns",
    "persist": "saving the rows",
    "persist_artifact": "saving the result",
    "extract": "reading the source",
    "shape": "cleaning at the source",
    "merge": "combining with earlier rows",
    "schema_drift": "checking for schema changes",
    "load_artifact": "reading the input dataset",
    "load_dataset": "reading the dataset",
    "finalize": "recording the new version",
}


def stage_words(stage: str) -> str:
    """A run's stage code as a person would say it: "parse" reads "reading the rows"."""
    if stage.startswith("apply_step_"):
        return f"applying step {stage.rsplit('_', 1)[1]}"
    return _STAGE_WORDS.get(stage, stage.replace("_", " "))


def _run_audit_notes(
    *,
    run: PipelineRun,
    summary: dict[str, Any] | None,
    events: list[dict[str, Any]],
    highlights: RunAuditHighlights,
) -> list[str]:
    notes: list[str] = []

    if run.status == "succeeded":
        notes.append("It finished without problems.")
    elif run.status == "failed":
        stage = highlights.failed_stage
        if stage:
            notes.append(f"It stopped while {stage_words(stage)}.")
        else:
            notes.append("It stopped with an error.")
    else:
        notes.append(f"It is {str(run.status).replace('_', ' ')}.")

    if highlights.derived_dataset_created:
        notes.append("It made a new dataset.")

    count = highlights.stage_count
    notes.append(f"It recorded {count} step{'' if count == 1 else 's'}.")

    if summary is None or (isinstance(summary, dict) and len(summary) == 0):
        notes.append("Some details of this run were not recorded.")

    seen: set[str] = set()
    ordered: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def build_run_audit_summary(*, run: PipelineRun) -> RunAuditSummary:
    summary = run.summary_json
    if summary is not None and not isinstance(summary, dict):
        summary = None
    summary_dict = summary if isinstance(summary, dict) else None

    events = _log_events(run.logs_json)
    highlights = RunAuditHighlights(
        stage_count=len(events),
        failed_stage=_infer_failed_stage(summary_dict, events),
        derived_dataset_created=_derived_dataset_created(summary_dict),
        ingestion_type=_ingestion_transformation_labels(summary_dict)[0],
        transformation_type=_ingestion_transformation_labels(summary_dict)[1],
    )

    warnings = _run_audit_notes(run=run, summary=summary_dict, events=events, highlights=highlights)

    return RunAuditSummary(
        id=run.id,
        run_type=run.run_type,
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        project_id=run.project_id,
        triggered_by_user_id=run.triggered_by_user_id,
        pipeline_id=run.pipeline_id,
        related_dataset_ids=extract_related_dataset_ids(summary_dict),
        summary_json=run.summary_json,
        logs_json=run.logs_json,
        highlights=highlights,
        warnings=warnings,
    )
