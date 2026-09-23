from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import DatasetVersion
from service_datasets.service import (
    create_derived_dataset_placeholder,
    finalize_dataset_materialization_success,
    get_dataset_model_for_project,
)
from service_ingestion.contracts import build_derived_dataset_path
from service_ingestion.parsers import parse_tabular_file
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_notifications.outcomes import notify_manual_transformation_run
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from service_transformations.contracts import get_transformation_pipeline_for_project
from service_transformations.dataset_access import build_step_context
from service_transformations.execution_context import ExecutionContext, VersionPin, head_pin
from service_transformations.executor import apply_single_step
from service_transformations.ir.clock import evaluation_instant, frozen_clock
from service_transformations.schemas import TransformationRunResponse
from service_transformations.validators import validate_steps_json
from shared_python.errors import ApplicationError, BadRequestError, InternalServerError
from shared_python.logging import get_logger
from shared_python.storage import content_digest

logger = get_logger(__name__)


def _log_event(stage: str, message: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
    event: dict[str, object] = {
        "stage": stage,
        "message": message,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if details:
        event["details"] = details
    return event


def _build_log_events(events: list[dict[str, object]]) -> dict[str, object]:
    return {"events": events}


def _dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


@dataclass(frozen=True)
class ReplayPlan:
    """Everything a replay substitutes for "the current state of things".

    Built by `replay.py` from a recorded execution context after it has pinned
    every input durably (§4). The run then reads the pinned base version's
    bytes instead of the head, the recorded steps instead of the pipeline's
    current ones, the pinned step datasets instead of their heads, and
    evaluates clock functions at the recorded instant.
    """

    original_run_id: uuid.UUID
    evaluated_at: datetime
    steps: list[dict[str, Any]]
    base_pin: VersionPin
    base_file_path: str
    base_file_type: str
    step_pins: list[VersionPin]
    step_overrides: dict[str, tuple[str, str]]


def run_saved_transformation_pipeline(
    db: Session,
    *,
    project_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
    notify_on_complete: bool = True,
    replay: ReplayPlan | None = None,
) -> TransformationRunResponse:
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    base_dataset = get_dataset_model_for_project(db, project_id, pipeline.base_dataset_id)

    # What this run reads and when it is evaluated is decided here, once, and
    # recorded (§3). A replay brings its own answers; an ordinary run reads the
    # head and freezes the clock now.
    if replay is not None:
        base_file_path, base_file_type = replay.base_file_path, replay.base_file_type
        evaluated_at = replay.evaluated_at
        steps_json = replay.steps
        input_pins: list[VersionPin] = [replay.base_pin, *replay.step_pins]
        step_overrides: dict[str, tuple[str, str]] | None = replay.step_overrides
        run_type = "dataset_transformation_replay"
    else:
        base_file_path, base_file_type = base_dataset.file_path, base_dataset.file_type
        # The real clock unless something outside already froze one (a replay
        # does, through ReplayPlan; a caller wanting several runs to share an
        # instant can too). Either way the run evaluates at exactly this value.
        evaluated_at = evaluation_instant()
        steps_json = pipeline.steps_json
        input_pins = [head_pin(db, base_dataset.id, role="base")]
        step_overrides = None
        run_type = "dataset_transformation"

    if not base_file_path or not base_file_type:
        raise BadRequestError("Base dataset has no stored file artifact.")

    context = ExecutionContext(
        evaluated_at=evaluated_at,
        steps=list(steps_json),
        inputs=input_pins,
        replay_of=str(replay.original_run_id) if replay is not None else None,
    )

    log_events: list[dict[str, object]] = [
        _log_event(
            "queued",
            "Transformation run accepted.",
            details={"pipeline_id": str(pipeline.id), "base_dataset_id": str(base_dataset.id)},
        )
    ]
    current_stage = "queued"

    run = create_pipeline_run(
        db,
        project_id=project_id,
        current_user=current_user,
        run_type=run_type,
        pipeline_id=pipeline.id,
        logs_json=_build_log_events(log_events),
    )

    log_events.append(_log_event("running", "Run started."))
    mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

    derived_dataset = None

    try:
        current_stage = "load_artifact"
        log_events.append(_log_event("load_artifact", "Reading base dataset from storage."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))
        try:
            file_bytes = storage_backend.read_bytes(base_file_path)
        except FileNotFoundError as exc:
            raise BadRequestError("Stored base dataset file was not found.") from exc
        except OSError as exc:
            raise BadRequestError(f"Unable to read base dataset file: {exc}") from exc

        if len(file_bytes) > settings.max_upload_size_bytes:
            raise BadRequestError("Base dataset file exceeds the configured maximum size.")

        current_stage = "parse"
        log_events.append(_log_event("parse", "Parsing tabular file."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))
        parsed = parse_tabular_file(file_bytes=file_bytes, file_type=base_file_type)
        source_frame = parsed.dataframe.copy()
        row_count_before = int(len(source_frame))
        column_count_before = int(len(source_frame.columns))

        steps = validate_steps_json(steps_json)
        working = source_frame.copy()
        warnings: list[str] = []
        step_context = build_step_context(
            db,
            project_id=project_id,
            storage_backend=storage_backend,
            max_bytes=settings.max_upload_size_bytes,
            pins=context.inputs,
            version_overrides=step_overrides,
        )

        # Every clock-dependent function reads the frozen instant for the whole
        # of the recipe, so `today()` in step 1 and step 5 agree, and a replay
        # of this run can install the same instant and get the same answer.
        with frozen_clock(evaluated_at):
            for index, step in enumerate(steps, start=1):
                current_stage = f"apply_step_{index}"
                log_events.append(
                    _log_event(
                        current_stage,
                        f"Applying step {index} ({step.step_type}).",
                        details={"step_type": step.step_type},
                    )
                )
                mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))
                working, step_warnings = apply_single_step(working, step, step_context)
                warnings.extend(step_warnings)

        row_count_after = int(len(working))
        column_count_after = int(len(working.columns))

        csv_bytes = _dataframe_to_csv_bytes(working)
        if len(csv_bytes) > settings.max_upload_size_bytes:
            raise BadRequestError("Transformed result exceeds the configured maximum output size.")

        current_stage = "materialize_profile"
        log_events.append(
            _log_event(
                "materialize_profile",
                "Inferring schema, preview, and profile for the transformed data.",
            )
        )
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))
        schema_json = infer_schema(dataframe=working)
        preview_json = build_preview(dataframe=working, limit=settings.preview_row_limit)
        profile_json = build_profile(
            dataframe=working,
            sample_limit=settings.profile_sample_value_limit,
            file_size_bytes=len(csv_bytes),
        )

        derived_name = _truncate_dataset_name(
            f"{pipeline.name} · replay" if replay is not None else f"{pipeline.name} · derived"
        )
        original_filename = "transformed.csv"

        current_stage = "persist_artifact"
        log_events.append(_log_event("persist_artifact", "Persisting derived dataset artifact."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        derived_dataset = create_derived_dataset_placeholder(
            db,
            project_id=project_id,
            parent_dataset_id=base_dataset.id,
            created_from_pipeline_id=pipeline.id,
            name=derived_name,
            original_filename=original_filename,
            file_type="csv",
            file_size_bytes=len(csv_bytes),
            source_id=None,
            current_user=current_user,
            pipeline_run_id=run.id,
        )

        relative_path, safe_name = build_derived_dataset_path(
            project_id=str(project_id),
            dataset_id=str(derived_dataset.id),
            basename=original_filename,
        )

        try:
            stored = storage_backend.save_upload(relative_path=relative_path, file_bytes=csv_bytes)
        except OSError as exc:
            db.delete(derived_dataset)
            db.flush()
            raise BadRequestError(f"Unable to store transformed file: {exc}") from exc

        current_stage = "finalize"
        log_events.append(_log_event("finalize", "Finalizing derived dataset record."))
        mark_pipeline_run_running(db, run=run, logs_json=_build_log_events(log_events))

        dataset_detail = finalize_dataset_materialization_success(
            db,
            dataset=derived_dataset,
            file_path=stored.relative_path,
            file_name=stored.file_name,
            schema_json=schema_json,
            schema_snapshot={"columns": schema_json["columns"]},
            preview_json=preview_json,
            profile_json=profile_json,
            row_count=profile_json["row_count"],
            column_count=profile_json["column_count"],
            content_hash=content_digest(csv_bytes),
            pipeline_run_id=run.id,
            created_by_user_id=current_user.id,
        )

        # The output pin: the version this run published, so a link to this run
        # resolves to what it produced -- not to whatever the head is later.
        published = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == derived_dataset.id,
                DatasetVersion.pipeline_run_id == run.id,
            )
        )
        context.outputs = [
            VersionPin(
                dataset_id=str(derived_dataset.id),
                version_number=published.version_number if published is not None else None,
                content_hash=published.content_hash if published is not None else None,
                role="output",
            )
        ]

        summary_json: dict[str, object] = {
            "transformation_type": "dataset_transformation",
            "execution_context": context.to_dict(),
            "pipeline_id": str(pipeline.id),
            "pipeline_name": pipeline.name,
            "pipeline": {"id": str(pipeline.id), "name": pipeline.name},
            "base_dataset": {
                "id": str(base_dataset.id),
                "name": base_dataset.name,
                "row_count": row_count_before,
                "column_count": column_count_before,
            },
            "derived_dataset": {
                "id": str(derived_dataset.id),
                "name": derived_dataset.name,
                "row_count": row_count_after,
                "column_count": column_count_after,
            },
            "step_count": len(steps),
            "row_count_before": row_count_before,
            "row_count_after": row_count_after,
            "column_count_before": column_count_before,
            "column_count_after": column_count_after,
            "warnings": warnings,
            "artifact": {
                "file_type": "csv",
                "file_size_bytes": len(csv_bytes),
                "stored_file_name": stored.file_name,
            },
        }

        log_events.append(_log_event("succeeded", "Transformation run completed successfully."))
        run_read = mark_pipeline_run_succeeded(
            db,
            run=run,
            summary_json=summary_json,
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_transformation_run(db, run_read=run_read, success=True)

        return TransformationRunResponse(run=run_read, dataset=dataset_detail)

    except ApplicationError as exc:
        log_events.append(
            _log_event(
                "failed",
                f"Transformation failed during {current_stage}.",
                details={"error": exc.detail, "failure_stage": current_stage},
            )
        )
        failed_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json={
                "transformation_type": "dataset_transformation",
                "execution_context": context.to_dict(),
                "failure_stage": current_stage,
                "pipeline_id": str(pipeline.id),
                "pipeline_name": pipeline.name,
                "pipeline": {"id": str(pipeline.id), "name": pipeline.name},
                "base_dataset": {"id": str(base_dataset.id), "name": base_dataset.name},
                "error": exc.detail,
            },
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_transformation_run(db, run_read=failed_read, success=False)
        raise

    except Exception as exc:
        logger.exception(
            "transformation_run_unexpected_error project_id=%s pipeline_id=%s stage=%s",
            project_id,
            pipeline_id,
            current_stage,
        )
        log_events.append(
            _log_event(
                "failed",
                f"Transformation failed during {current_stage}.",
                details={"error": str(exc), "failure_stage": current_stage},
            )
        )
        failed_read = mark_pipeline_run_failed(
            db,
            run=run,
            summary_json={
                "transformation_type": "dataset_transformation",
                "execution_context": context.to_dict(),
                "failure_stage": current_stage,
                "pipeline_id": str(pipeline.id),
                "pipeline_name": pipeline.name,
                "pipeline": {"id": str(pipeline.id), "name": pipeline.name},
                "base_dataset": {"id": str(base_dataset.id), "name": base_dataset.name},
                "error": "An unexpected error occurred during transformation.",
            },
            logs_json=_build_log_events(log_events),
        )
        if notify_on_complete:
            notify_manual_transformation_run(db, run_read=failed_read, success=False)
        raise InternalServerError("Transformation failed due to an unexpected error.") from exc


def _truncate_dataset_name(name: str, *, max_length: int = 160) -> str:
    cleaned = name.strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."
