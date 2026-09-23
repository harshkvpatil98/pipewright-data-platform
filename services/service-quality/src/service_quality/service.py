"""Data quality rule management and dataset evaluation."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import (
    create_derived_dataset_placeholder,
    finalize_dataset_materialization_success,
    get_dataset_model_for_project,
)
from service_ingestion.contracts import build_derived_dataset_path
from service_ingestion.parsers import parse_tabular_file
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_projects.contracts import ensure_owned_project
from service_quality.engine import RulesetResult, evaluate_rule, evaluate_ruleset
from service_quality.models import DataQualityRule, DataQualityRunResult
from service_quality.schemas import (
    AdHocRuleCheck,
    DataQualityEvaluationRequest,
    DataQualityEvaluationResponse,
    DataQualityResultListResponse,
    DataQualityResultRead,
    DataQualityRuleCreate,
    DataQualityRuleListResponse,
    DataQualityRuleRead,
    DataQualityRuleUpdate,
    RuleResultRead,
)
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger
from shared_python.storage import content_digest

logger = get_logger(__name__)

MAX_RESULT_HISTORY = 200


def _load_dataset_frame(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, storage_backend: Any) -> tuple[Any, pd.DataFrame]:
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("Dataset has no stored file artifact to evaluate.")
    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise NotFoundError(
            "This dataset's stored file is missing. The dataset record still exists, so re-uploading the file restores it."
        ) from exc
    except OSError as exc:
        raise BadRequestError(f"Unable to read dataset file: {exc}") from exc
    return dataset, parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type).dataframe


def get_rule_for_project(db: Session, project_id: uuid.UUID, rule_id: uuid.UUID) -> DataQualityRule:
    rule = db.scalar(
        select(DataQualityRule).where(
            DataQualityRule.id == rule_id, DataQualityRule.project_id == project_id
        )
    )
    if rule is None:
        raise NotFoundError("Data quality rule not found.")
    return rule


def list_rules(
    db: Session, project_id: uuid.UUID, current_user: UserRead, *, dataset_id: uuid.UUID | None = None
) -> DataQualityRuleListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(DataQualityRule).where(DataQualityRule.project_id == project_id)
    if dataset_id is not None:
        # Dataset-specific rules plus project-wide rules that apply to everything.
        statement = statement.where(
            (DataQualityRule.dataset_id == dataset_id) | (DataQualityRule.dataset_id.is_(None))
        )
    rows = db.scalars(statement.order_by(DataQualityRule.created_at.desc())).all()
    return DataQualityRuleListResponse(
        items=[DataQualityRuleRead.model_validate(row, from_attributes=True) for row in rows]
    )


def create_rule(
    db: Session, project_id: uuid.UUID, payload: DataQualityRuleCreate, current_user: UserRead
) -> DataQualityRuleRead:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.dataset_id is not None:
        get_dataset_model_for_project(db, project_id, payload.dataset_id)

    rule = DataQualityRule(
        project_id=project_id,
        dataset_id=payload.dataset_id,
        name=payload.name.strip(),
        description=payload.description,
        rule_type=payload.rule_type,
        severity=payload.severity,
        config_json=dict(payload.config),
        created_by_user_id=current_user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return DataQualityRuleRead.model_validate(rule, from_attributes=True)


def update_rule(
    db: Session,
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: DataQualityRuleUpdate,
    current_user: UserRead,
) -> DataQualityRuleRead:
    ensure_owned_project(db, project_id, current_user.id)
    rule = get_rule_for_project(db, project_id, rule_id)

    if payload.name is not None:
        rule.name = payload.name.strip()
    if payload.description is not None:
        rule.description = payload.description
    if payload.severity is not None:
        rule.severity = payload.severity
    if payload.config is not None:
        rule.config_json = dict(payload.config)
    if payload.enabled is not None:
        rule.enabled = payload.enabled

    db.commit()
    db.refresh(rule)
    return DataQualityRuleRead.model_validate(rule, from_attributes=True)


def delete_rule(db: Session, project_id: uuid.UUID, rule_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    rule = get_rule_for_project(db, project_id, rule_id)
    db.delete(rule)
    db.commit()


def check_rule_ad_hoc(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: AdHocRuleCheck,
    current_user: UserRead,
    storage_backend: Any,
) -> RuleResultRead:
    """Evaluate an unsaved rule so operators can tune it before committing."""
    ensure_owned_project(db, project_id, current_user.id)
    _, frame = _load_dataset_frame(db, project_id, dataset_id, storage_backend)

    evaluation = evaluate_rule(frame, rule_type=payload.rule_type, config=payload.config)
    return RuleResultRead(
        rule_id=None,
        name=f"ad hoc {payload.rule_type}",
        rule_type=payload.rule_type,
        severity=payload.severity,
        status=evaluation.status,
        evaluated_rows=evaluation.evaluated_rows,
        failed_rows=evaluation.failed_rows,
        failure_rate=evaluation.failure_rate,
        message=evaluation.message,
        details=evaluation.details,
    )


def _dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def _materialise_quarantine_dataset(
    db: Session,
    *,
    project_id: uuid.UUID,
    source_dataset: Any,
    frame: pd.DataFrame,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
) -> uuid.UUID | None:
    """Persist quarantined rows as their own dataset for inspection and replay."""
    if frame.empty:
        return None

    csv_bytes = _dataframe_to_csv_bytes(frame)
    if len(csv_bytes) > settings.max_upload_size_bytes:
        raise BadRequestError("Quarantined rows exceed the configured maximum dataset size.")

    dataset = create_derived_dataset_placeholder(
        db,
        project_id=project_id,
        parent_dataset_id=source_dataset.id,
        created_from_pipeline_id=None,
        name=f"{source_dataset.name} · quarantine"[:160],
        original_filename="quarantine.csv",
        file_type="csv",
        file_size_bytes=len(csv_bytes),
        source_id=source_dataset.source_id,
        current_user=current_user,
        pipeline_run_id=None,
    )

    relative_path, _ = build_derived_dataset_path(
        project_id=str(project_id), dataset_id=str(dataset.id), basename="quarantine.csv"
    )
    try:
        stored = storage_backend.save_upload(relative_path=relative_path, file_bytes=csv_bytes)
    except OSError as exc:
        db.delete(dataset)
        db.flush()
        raise BadRequestError(f"Unable to store quarantined rows: {exc}") from exc

    schema_json = infer_schema(dataframe=frame)
    detail = finalize_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=stored.relative_path,
        file_name=stored.file_name,
        schema_json=schema_json,
        schema_snapshot={"columns": schema_json["columns"]},
        preview_json=build_preview(dataframe=frame, limit=settings.preview_row_limit),
        profile_json=build_profile(
            dataframe=frame,
            sample_limit=settings.profile_sample_value_limit,
            file_size_bytes=len(csv_bytes),
        ),
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        content_hash=content_digest(csv_bytes),
        created_by_user_id=current_user.id,
    )
    return detail.id


def _persist_results(
    db: Session,
    *,
    project_id: uuid.UUID,
    evaluation_id: uuid.UUID,
    dataset_id: uuid.UUID,
    result: RulesetResult,
    pipeline_run_id: uuid.UUID | None = None,
) -> None:
    for evaluated in result.results:
        db.add(
            DataQualityRunResult(
                project_id=project_id,
                evaluation_id=evaluation_id,
                rule_id=uuid.UUID(evaluated.rule_id) if evaluated.rule_id else None,
                dataset_id=dataset_id,
                pipeline_run_id=pipeline_run_id,
                rule_name=evaluated.name[:160],
                rule_type=evaluated.rule_type,
                severity=evaluated.severity,
                status=evaluated.evaluation.status,
                evaluated_rows=evaluated.evaluation.evaluated_rows,
                failed_rows=evaluated.evaluation.failed_rows,
                failure_rate=evaluated.evaluation.failure_rate,
                message=evaluated.evaluation.message[:2000],
                details_json=evaluated.evaluation.details,
            )
        )


def evaluate_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DataQualityEvaluationRequest,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
) -> DataQualityEvaluationResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset, frame = _load_dataset_frame(db, project_id, dataset_id, storage_backend)

    statement = select(DataQualityRule).where(
        DataQualityRule.project_id == project_id,
        DataQualityRule.enabled.is_(True),
        (DataQualityRule.dataset_id == dataset_id) | (DataQualityRule.dataset_id.is_(None)),
    )
    if payload.rule_ids:
        statement = statement.where(DataQualityRule.id.in_(payload.rule_ids))

    rules = db.scalars(statement.order_by(DataQualityRule.created_at)).all()
    if not rules:
        raise BadRequestError("No enabled data quality rules apply to this dataset.")

    result = evaluate_ruleset(
        frame,
        [
            {
                "id": rule.id,
                "name": rule.name,
                "rule_type": rule.rule_type,
                "severity": rule.severity,
                "config": dict(rule.config_json or {}),
            }
            for rule in rules
        ],
        quarantine=payload.quarantine,
    )

    evaluation_id = uuid.uuid4()
    quarantine_dataset_id = None
    if payload.quarantine and not result.quarantined_frame.empty:
        quarantine_dataset_id = _materialise_quarantine_dataset(
            db,
            project_id=project_id,
            source_dataset=dataset,
            frame=result.quarantined_frame,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    _persist_results(
        db,
        project_id=project_id,
        evaluation_id=evaluation_id,
        dataset_id=dataset_id,
        result=result,
    )

    evaluated_at = datetime.now(UTC)
    status_by_rule = {r.rule_id: r.evaluation.status for r in result.results if r.rule_id}
    for rule in rules:
        rule.last_evaluated_at = evaluated_at
        rule.last_status = status_by_rule.get(str(rule.id))

    db.commit()

    summary = result.to_summary()
    return DataQualityEvaluationResponse(
        evaluation_id=evaluation_id,
        dataset_id=dataset_id,
        status=result.status,
        rules_evaluated=summary["rules_evaluated"],
        rules_failed=summary["rules_failed"],
        error_failures=summary["error_failures"],
        warning_failures=summary["warning_failures"],
        rows_in=summary["rows_in"],
        rows_passing=summary["rows_passing"],
        rows_quarantined=summary["rows_quarantined"],
        quarantine_dataset_id=quarantine_dataset_id,
        results=[RuleResultRead(**item) for item in summary["results"]],
        warnings=result.warnings,
    )


def list_results(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    dataset_id: uuid.UUID | None = None,
    limit: int = 50,
) -> DataQualityResultListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(DataQualityRunResult).where(DataQualityRunResult.project_id == project_id)
    if dataset_id is not None:
        statement = statement.where(DataQualityRunResult.dataset_id == dataset_id)
    rows = db.scalars(
        statement.order_by(DataQualityRunResult.created_at.desc()).limit(min(limit, MAX_RESULT_HISTORY))
    ).all()
    return DataQualityResultListResponse(
        items=[DataQualityResultRead.model_validate(row, from_attributes=True) for row in rows]
    )


def total_quality_rules(db: Session) -> int:
    return db.scalar(select(func.count(DataQualityRule.id))) or 0


def failing_rule_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(DataQualityRule.id)).where(DataQualityRule.last_status == "failed")
        )
        or 0
    )
