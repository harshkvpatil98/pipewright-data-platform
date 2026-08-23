"""Suggestions, detection, and explanation over real datasets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_intelligence import documenting, joins, matching, phrasing, pii, rules
from service_intelligence.schemas import (
    DescribeRequest,
    DescribeResponse,
    DocumentationResponse,
    DraftRead,
    DuplicateRequest,
    DuplicateResponse,
    ExplainResponse,
    ExplanationCandidateRead,
    JoinCandidateRead,
    JoinSuggestionRequest,
    JoinSuggestionResponse,
    MaskingRequest,
    MaskingResponse,
    MatchCandidateRead,
    ParsedIntentRead,
    PiiFindingRead,
    PiiScanResponse,
    RuleSuggestionRead,
    RuleSuggestionResponse,
)

# Enough rows to judge a column by; more is slower without being more accurate.
SAMPLE_ROWS = 5_000
MAX_ANALYSED_ROWS = 500_000


def _get_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def _load_frame(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, storage) -> pd.DataFrame:
    from service_ingestion.parsers import parse_tabular_file

    dataset = _get_dataset(db, project_id, dataset_id)
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError(f"'{dataset.name}' has no stored file to analyse.")

    try:
        payload = storage.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise BadRequestError(f"The stored file for '{dataset.name}' is missing.") from exc

    frame = parse_tabular_file(file_bytes=payload, file_type=dataset.file_type).dataframe
    if len(frame) > MAX_ANALYSED_ROWS:
        raise BadRequestError(
            f"'{dataset.name}' has {len(frame):,} rows, above the {MAX_ANALYSED_ROWS:,} "
            "limit for this analysis."
        )
    return frame


def _columns(dataset: Dataset) -> list[str]:
    for candidate in (dataset.schema_json, dataset.schema_snapshot):
        if isinstance(candidate, dict):
            ordered = candidate.get("ordered_columns")
            if isinstance(ordered, list) and ordered:
                return [str(name) for name in ordered]
    return []


# --------------------------------------------------------------------------
# PII
# --------------------------------------------------------------------------


def scan_pii(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead, storage
) -> PiiScanResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)
    frame = _load_frame(db, project_id, dataset_id, storage).head(SAMPLE_ROWS)

    samples = {
        str(column): frame[column].dropna().tolist() for column in frame.columns
    }
    findings = pii.scan_dataset(samples)

    high = [item for item in findings if item.confidence == "high"]
    if not findings:
        summary = (
            f"Nothing in {dataset.name} looks like personal data. Note that this "
            "recognises known formats; an unusual national ID format would be missed."
        )
    else:
        summary = (
            f"{len(findings)} column(s) in {dataset.name} look like personal data"
            + (f", {len(high)} of them clearly." if high else ", none of them clearly.")
            + " Nothing has been masked."
        )

    return PiiScanResponse(
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        findings=[PiiFindingRead(**finding.to_dict()) for finding in findings],
        columns_scanned=len(samples),
        summary=summary,
    )


def build_masking(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: MaskingRequest,
    current_user: UserRead,
) -> MaskingResponse:
    """The step a masking decision becomes. Returned, never applied."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    detector = pii.DETECTORS_BY_KIND.get(payload.kind)
    if detector is None:
        raise BadRequestError(
            f"Unknown kind '{payload.kind}'. Known: {', '.join(sorted(pii.DETECTORS_BY_KIND))}."
        )
    if payload.column not in _columns(dataset):
        raise BadRequestError(f"'{dataset.name}' has no column called '{payload.column}'.")

    finding = pii.PiiFinding(
        column=payload.column,
        kind=payload.kind,
        label=detector.label,
        confidence="high",
        name_matched=True,
        value_match_rate=1.0,
        sample_size=0,
        suggested_strategy=detector.default_strategy,
        reason="Chosen by hand.",
        guidance=detector.guidance,
    )
    strategy = payload.strategy or detector.default_strategy
    step = pii.masking_step(finding, strategy=strategy)

    return MaskingResponse(
        column=payload.column,
        strategy=strategy,  # type: ignore[arg-type]
        step=step,
        note=(
            "Add this step to a pipeline to apply it. Masking is destructive, "
            "so it is not applied to the dataset here."
        ),
    )


# --------------------------------------------------------------------------
# Joins
# --------------------------------------------------------------------------


def suggest_joins(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: JoinSuggestionRequest,
    current_user: UserRead,
    storage,
) -> JoinSuggestionResponse:
    ensure_owned_project(db, project_id, current_user.id)
    if dataset_id == payload.right_dataset_id:
        raise BadRequestError("A dataset cannot be joined to itself here.")

    left_name = _get_dataset(db, project_id, dataset_id).name
    right_name = _get_dataset(db, project_id, payload.right_dataset_id).name

    left_frame = _load_frame(db, project_id, dataset_id, storage).head(SAMPLE_ROWS)
    right_frame = _load_frame(db, project_id, payload.right_dataset_id, storage).head(SAMPLE_ROWS)

    candidates = joins.suggest_join_keys(
        [joins.ColumnProfile(str(column), left_frame[column].tolist()) for column in left_frame.columns],
        [joins.ColumnProfile(str(column), right_frame[column].tolist()) for column in right_frame.columns],
        limit=payload.limit,
    )

    reads = [
        JoinCandidateRead(
            **candidate.to_dict(),
            step=joins.build_join_step(candidate, right_dataset_id=str(payload.right_dataset_id)),
        )
        for candidate in candidates
    ]

    if not reads:
        summary = (
            f"No column in {left_name} shares enough values with {right_name} to join on. "
            "They may not be related, or the keys may be formatted differently."
        )
    else:
        best = reads[0]
        summary = (
            f"'{best.left_column}' to '{best.right_column}' looks like the join: "
            f"{best.explanation}"
        )

    return JoinSuggestionResponse(
        left_dataset_id=dataset_id,
        right_dataset_id=payload.right_dataset_id,
        candidates=reads,
        summary=summary,
    )


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


def find_duplicates(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DuplicateRequest,
    current_user: UserRead,
    storage,
) -> DuplicateResponse:
    ensure_owned_project(db, project_id, current_user.id)
    frame = _load_frame(db, project_id, dataset_id, storage).head(SAMPLE_ROWS)

    if payload.column not in frame.columns:
        raise BadRequestError(
            f"No column called '{payload.column}'. This dataset has: "
            f"{', '.join(str(column) for column in frame.columns)}."
        )

    report = matching.find_duplicates(
        frame[payload.column].tolist(),
        column=payload.column,
        threshold=payload.threshold,
        limit=payload.limit,
    )
    plan = matching.merge_plan(report.candidates)

    return DuplicateResponse(
        dataset_id=dataset_id,
        column=report.column,
        distinct_values=report.distinct_values,
        candidates=[MatchCandidateRead(**item.to_dict()) for item in report.candidates],
        comparisons=report.comparisons,
        truncated=report.truncated,
        summary=report.summary,
        merge_step=matching.build_merge_step(report.column, plan) if plan else None,
    )


# --------------------------------------------------------------------------
# Describe to build
# --------------------------------------------------------------------------


def describe_to_steps(
    db: Session, project_id: uuid.UUID, payload: DescribeRequest, current_user: UserRead
) -> DescribeResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, payload.dataset_id)

    columns = _columns(dataset)
    if not columns:
        raise BadRequestError(
            f"'{dataset.name}' has no recorded columns yet, so there is nothing to build against."
        )

    result = phrasing.parse(payload.sentence, columns)
    return DescribeResponse(
        dataset_id=payload.dataset_id,
        steps=result.steps,
        understood=[ParsedIntentRead(**item.to_dict()) for item in result.understood],
        not_understood=result.not_understood,
        unknown_columns=result.unknown_columns,
        complete=result.complete,
        summary=result.summary,
    )


# --------------------------------------------------------------------------
# Explanation
# --------------------------------------------------------------------------


def explain_metric(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    metric: str,
    current_user: UserRead,
    *,
    window_days: int = 2,
) -> ExplainResponse:
    """What else changed around the time a metric moved."""
    ensure_owned_project(db, project_id, current_user.id)
    _get_dataset(db, project_id, dataset_id)

    from service_observability.models import DatasetMetric

    points = list(
        db.scalars(
            select(DatasetMetric)
            .where(
                DatasetMetric.dataset_id == dataset_id,
                DatasetMetric.metric_key == metric,
                DatasetMetric.column_name.is_(None),
            )
            .order_by(DatasetMetric.captured_at.desc())
            .limit(2)
        ).all()
    )
    if not points:
        raise BadRequestError(
            f"No '{metric}' has been recorded for this dataset, so there is no change to explain."
        )

    latest = points[0]
    previous = points[1].value if len(points) > 1 else None
    changed_at = latest.captured_at
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=UTC)

    window = timedelta(days=window_days)
    events = _timeline(db, project_id, dataset_id, changed_at, window)

    report = explanation_module().explain(
        metric=metric,
        changed_at=changed_at,
        before=previous,
        after=latest.value,
        events=events,
        window=window,
    )

    return ExplainResponse(
        dataset_id=dataset_id,
        metric=report.metric,
        change_description=report.change_description,
        candidates=[
            ExplanationCandidateRead(**candidate.to_dict()) for candidate in report.candidates
        ],
        summary=report.summary,
        searched_events=report.searched_events,
    )


def explanation_module():
    from service_intelligence import explanation

    return explanation


def _timeline(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    around: datetime,
    window: timedelta,
) -> list[Any]:
    """Everything recorded near a moment that might explain it."""
    from service_governance.models import ResourceVersion
    from service_quality.models import DataQualityRunResult, SchemaDriftEvent

    from service_intelligence.explanation import TimelineEvent

    since, until = around - window, around + window
    events: list[TimelineEvent] = []

    for version in db.scalars(
        select(ResourceVersion).where(
            ResourceVersion.project_id == project_id,
            ResourceVersion.created_at >= since,
            ResourceVersion.created_at <= until,
        )
    ).all():
        events.append(
            TimelineEvent(
                kind="pipeline_edit" if version.resource_type == "pipeline" else "workflow_edit",
                at=version.created_at,
                summary=version.change_summary or f"{version.name} was edited",
                detail={"resource_type": version.resource_type, "version": version.version},
            )
        )

    for drift in db.scalars(
        select(SchemaDriftEvent).where(
            SchemaDriftEvent.project_id == project_id,
            SchemaDriftEvent.created_at >= since,
            SchemaDriftEvent.created_at <= until,
        )
    ).all():
        events.append(
            TimelineEvent(
                kind="schema_drift",
                at=drift.created_at,
                summary=drift.summary,
                detail={"severity": drift.severity},
            )
        )

    for result in db.scalars(
        select(DataQualityRunResult).where(
            DataQualityRunResult.dataset_id == dataset_id,
            DataQualityRunResult.status == "failed",
            DataQualityRunResult.created_at >= since,
            DataQualityRunResult.created_at <= until,
        )
    ).all():
        events.append(
            TimelineEvent(
                kind="quality_failure",
                at=result.created_at,
                summary=f"{result.rule_name or 'A rule'} failed",
                detail={"failed_rows": result.failed_rows},
            )
        )

    return events


# --------------------------------------------------------------------------
# Documentation and rules
# --------------------------------------------------------------------------


def draft_documentation(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DocumentationResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)
    profile = dataset.profile_json if isinstance(dataset.profile_json, dict) else {}
    flags = profile.get("quality_flags") if isinstance(profile.get("quality_flags"), dict) else {}

    facts = documenting.DatasetFacts(
        name=dataset.name,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        columns=_columns(dataset),
        completeness=profile.get("completeness_score"),
        duplicate_percentage=profile.get("duplicate_row_percentage"),
        is_derived=bool(dataset.is_derived),
        produced_by=_producing_pipeline_name(db, dataset),
        upstream_names=_upstream_names(db, dataset),
        high_null_columns=list(flags.get("high_null_columns") or []),
        identifier_columns=list(flags.get("potential_id_columns") or []),
        rule_count=_rule_count(db, project_id, dataset_id),
        certified=_is_certified(db, dataset_id),
    )

    dataset_draft = documenting.describe_dataset(facts)
    column_drafts = [
        documenting.describe_column(
            documenting.ColumnFacts(
                name=str(entry.get("name")),
                inferred_type=entry.get("inferred_type"),
                null_percentage=entry.get("null_percentage"),
                unique_count=entry.get("unique_count"),
                row_count=dataset.row_count,
                sample_values=list(entry.get("sample_values") or [])[:3],
                possible_identifier=bool(entry.get("possible_identifier")),
            )
        )
        for entry in (profile.get("columns") or [])
        if isinstance(entry, dict) and entry.get("name")
    ]

    return DocumentationResponse(
        dataset_id=dataset_id,
        dataset=DraftRead(**dataset_draft.to_dict()),
        columns=[DraftRead(**draft.to_dict()) for draft in column_drafts],
        summary=(
            f"A draft description of {dataset.name} and {len(column_drafts)} column(s), "
            "assembled from facts already recorded. Edit before accepting."
        ),
    )


def _producing_pipeline_name(db: Session, dataset: Dataset) -> str | None:
    if dataset.created_from_pipeline_id is None:
        return None
    from service_transformations.models import TransformationPipeline

    pipeline = db.get(TransformationPipeline, dataset.created_from_pipeline_id)
    return pipeline.name if pipeline else None


def _upstream_names(db: Session, dataset: Dataset) -> list[str]:
    if dataset.parent_dataset_id is None:
        return []
    parent = db.get(Dataset, dataset.parent_dataset_id)
    return [parent.name] if parent else []


def _rule_count(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> int:
    from sqlalchemy import func

    from service_quality.models import DataQualityRule

    return (
        db.scalar(
            select(func.count(DataQualityRule.id)).where(
                DataQualityRule.project_id == project_id,
                DataQualityRule.dataset_id == dataset_id,
            )
        )
        or 0
    )


def _is_certified(db: Session, dataset_id: uuid.UUID) -> bool:
    try:
        from service_reporting.models import CatalogAnnotation

        note = db.scalar(
            select(CatalogAnnotation).where(CatalogAnnotation.dataset_id == dataset_id)
        )
        return bool(note and note.certified)
    except ImportError:  # pragma: no cover - reporting is optional
        return False


def suggest_quality_rules(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> RuleSuggestionResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    suggestions = rules.suggest_rules(dataset.profile_json)
    return RuleSuggestionResponse(
        dataset_id=dataset_id,
        items=[RuleSuggestionRead(**item.to_dict()) for item in suggestions],
        summary=rules.summarise(suggestions),
    )
