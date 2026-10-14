"""Execute an extraction job: pull rows, merge, profile, and persist a dataset.

Mirrors the shape of the file-upload ingestion runner so extraction runs appear
in the same pipeline_runs history, with the same staged log events, as every
other operation on the platform.
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import (
    create_uploaded_dataset_placeholder,
    finalize_dataset_materialization_success,
    get_dataset_model_for_project,
    reusable_dataset,
)
from service_extraction.connectors import sql_database
from service_extraction.shaping import shape_rows
from service_extraction import connector_sources as sources
from service_extraction.incremental import build_incremental_query, compute_watermark, merge_frames
from service_extraction.models import ExtractionJob
from service_extraction.schemas import ExtractionJobRead, ExtractionRunResponse
from service_extraction.service import get_connection_for_project, get_job_for_project, resolve_job_query
from service_ingestion.contracts import build_derived_dataset_path
from service_ingestion.read_copy import frame_of
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from service_quality.drift import detect_schema_drift
from service_quality.drift_service import record_drift_event
from shared_python.errors import ApplicationError, BadRequestError, InternalServerError
from shared_python.logging import get_logger
from shared_python.security.config_crypto import decrypt_sensitive_fields
from shared_python.storage import content_digest

from service_extraction.tiers import note_for

logger = get_logger(__name__)

RUN_TYPE = "database_extraction"


_LOAD_WORDS = {
    "full_refresh": "replacing everything",
    "incremental_append": "adding new rows",
    "incremental_merge": "updating matching rows",
}


def _stage_words(stage: str) -> str:
    """The step an import was on, as the person reading its history would say it."""
    return {
        "queued": "starting",
        "extract": "reading the source",
        "shape": "cleaning at the source",
        "merge": "combining with earlier rows",
        "profile": "working out the columns",
        "schema_drift": "checking for schema changes",
        "persist": "saving the rows",
    }.get(stage, "running")


def _log_event(stage: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "stage": stage,
        "message": message,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if details:
        event["details"] = details
    return event


def _dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def _load_existing_frame(job: ExtractionJob, db: Session, storage_backend: Any) -> pd.DataFrame:
    """Read the dataset this job maintains, for append/merge modes."""
    if job.target_dataset_id is None:
        return pd.DataFrame()
    try:
        dataset = get_dataset_model_for_project(db, job.project_id, job.target_dataset_id)
    except Exception:  # noqa: BLE001 - a deleted target simply means "start fresh"
        return pd.DataFrame()
    if not dataset.file_path or not dataset.file_type:
        return pd.DataFrame()
    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except (FileNotFoundError, OSError):
        return pd.DataFrame()
    return frame_of(storage_backend, dataset.file_path, file_bytes, file_type=dataset.file_type, spec=dataset.ingest_spec_json)


def run_extraction_job(
    db: Session,
    *,
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
) -> ExtractionRunResponse:
    ensure_owned_project(db, project_id, current_user.id)
    job = get_job_for_project(db, project_id, job_id)
    connection = get_connection_for_project(db, project_id, job.connection_id)

    if not job.enabled:
        raise BadRequestError("This import is switched off. Switch it on to run it.")

    log_events = [
        _log_event(
            "queued",
            "Waiting to start.",
            details={"job_id": str(job.id), "connection": connection.name, "load_mode": job.load_mode},
        )
    ]
    current_stage = "queued"

    run = create_pipeline_run(
        db,
        project_id=project_id,
        current_user=current_user,
        run_type=RUN_TYPE,
        pipeline_id=None,
        logs_json={"events": log_events},
    )
    log_events.append(_log_event("running", "Run started."))
    mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})

    try:
        config = decrypt_sensitive_fields(
            dict(connection.config_json or {}), sources.secret_fields(connection.connector_type)
        )
        connector_cursor: str | None = None
        shaping_plan: dict[str, Any] | None = None
        if not sources.is_sql(connection.connector_type):
            # Any other connector reads through the SDK. It keeps its own place:
            # "only new rows" resumes from the cursor its last read handed back.
            current_stage = "extract"
            log_events.append(
                _log_event(
                    "extract",
                    f"Reading {sources.stream_label(job.stream_json)} from {sources.spec(connection.connector_type).label}.",
                    details={"load_mode": job.load_mode, "resume_from": job.watermark_value},
                )
            )
            mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})
            read = sources.read(
                connection.connector_type,
                config,
                job.stream_json,
                limit=job.max_rows,
                cursor=job.watermark_value if job.load_mode != "full_refresh" else None,
            )
            incoming = read.dataframe
            # The connector's own tier note is already among its warnings.
            warnings = list(read.warnings)
            result = SimpleNamespace(row_count=int(read.row_count), truncated=bool(read.truncated))
            connector_cursor = read.next_cursor
        else:
            base_query = resolve_job_query(
                connection.connector_type,
                source_kind=job.source_kind,
                table=job.source_table,
                schema=job.source_schema,
                query_sql=job.query_sql,
            )

            params: dict[str, Any] = {}
            statement = base_query
            if job.load_mode != "full_refresh":
                statement, params = build_incremental_query(
                    connection.connector_type,
                    base_query=base_query,
                    cursor_column=job.cursor_column or "",
                    watermark=job.watermark_value,
                )

            current_stage = "extract"
            log_events.append(
                _log_event(
                    "extract",
                    "Reading rows from the source database.",
                    details={
                        "load_mode": job.load_mode,
                        "incremental_from": job.watermark_value,
                    },
                )
            )
            mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})

            # The incremental wrapper is generated by us around already-validated SQL,
            # so it is not re-checked as though it were operator input.
            def _read(sql: str, *, validate: bool):
                return sql_database.read_dataframe(
                    connection.connector_type,
                    config,
                    sql=sql,
                    params=params,
                    max_rows=job.max_rows,
                    validate_read_only=validate,
                )

            shaping_plan: dict[str, Any] | None = None
            steps = list(job.steps_json or [])
            if steps:
                # Shape at the source (Phase 12 pushdown, wired in): the pushable
                # prefix of the job's steps runs in the database around the job's
                # own query; the rest runs here on what comes back.
                current_stage = "shape"
                log_events.append(
                    _log_event("shape", f"Applying {len(steps)} cleaning step{'' if len(steps) == 1 else 's'}, at the source where it can.")
                )
                mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})
                plain_result: list[Any] = []

                def _read_all() -> pd.DataFrame:
                    plain_result.append(_read(statement, validate=(job.load_mode == "full_refresh")))
                    return plain_result[-1].dataframe

                shaped = shape_rows(
                    steps=steps,
                    connector_type=connection.connector_type,
                    base_query=statement,
                    read_sql=lambda sql: _read(sql, validate=False).dataframe,
                    read_all=_read_all,
                )
                incoming = shaped.frame
                warnings = list(shaped.warnings)
                if plain_result:
                    warnings.extend(plain_result[-1].warnings)
                shaping_plan = shaped.plan
                result = SimpleNamespace(
                    row_count=int(len(incoming)),
                    truncated=bool(plain_result[-1].truncated) if plain_result else False,
                )
            else:
                result = _read(statement, validate=(job.load_mode == "full_refresh"))
                incoming = result.dataframe
                warnings = list(result.warnings)
            # The tier travels into the run's own output: by the time anybody is
            # looking at these numbers, the connector picker is long gone.
            tier_note = note_for(connection.connector_type)
            if tier_note:
                warnings.append(tier_note)

        current_stage = "merge"
        log_events.append(
            _log_event("merge", f"Combining with what was loaded before ({_LOAD_WORDS.get(job.load_mode, job.load_mode)}).", details={"rows_extracted": result.row_count})
        )
        mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})

        existing = _load_existing_frame(job, db, storage_backend) if job.load_mode != "full_refresh" else pd.DataFrame()
        merged = merge_frames(
            existing,
            incoming,
            load_mode=job.load_mode,
            primary_key_columns=list(job.primary_key_columns or []),
        )
        warnings.extend(merged.warnings)
        working = merged.dataframe

        csv_bytes = _dataframe_to_csv_bytes(working)
        if len(csv_bytes) > settings.max_upload_size_bytes:
            raise BadRequestError(
                "Extracted result exceeds the configured maximum size. "
                "Narrow the query, lower max_rows, or switch to an incremental load."
            )

        current_stage = "profile"
        log_events.append(_log_event("profile", "Working out the columns and a preview."))
        mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})
        schema_json = infer_schema(dataframe=working)
        preview_json = build_preview(dataframe=working, limit=settings.preview_row_limit)
        profile_json = build_profile(
            dataframe=working,
            sample_limit=settings.profile_sample_value_limit,
            file_size_bytes=len(csv_bytes),
        )

        # Compare against the schema this job last produced, before the target
        # pointer moves to the new dataset.
        current_stage = "schema_drift"
        previous_dataset_id = job.target_dataset_id
        drift_report = None
        if previous_dataset_id is not None:
            try:
                previous_dataset = get_dataset_model_for_project(db, project_id, previous_dataset_id)
                drift_report = detect_schema_drift(previous_dataset.schema_json, schema_json)
            except Exception:  # noqa: BLE001 - drift reporting must never fail a run
                logger.exception("extraction_drift_check_failed job_id=%s", job.id)
                drift_report = None

        if drift_report is not None and drift_report.has_drift:
            log_events.append(
                _log_event(
                    "schema_drift",
                    f"Schema drift detected ({drift_report.severity}): {drift_report.summary}",
                    details=drift_report.to_dict(),
                )
            )
            warnings.append(f"Schema drift ({drift_report.severity}): {drift_report.summary}")

        current_stage = "persist"
        log_events.append(_log_event("persist", "Saving the rows."))
        mark_pipeline_run_running(db, run=run, logs_json={"events": log_events})

        # One dataset per import: the first run creates it and every later run
        # adds a version to it, so a nightly import is one dataset with a
        # history rather than 365 look-alikes. Only when that dataset has been
        # deleted does a run start a new one.
        dataset = reusable_dataset(db, project_id, job.target_dataset_id)
        if dataset is not None:
            dataset.file_type = "csv"
            dataset.file_size_bytes = len(csv_bytes)
            dataset.pipeline_run_id = run.id
        else:
            dataset = create_uploaded_dataset_placeholder(
                db,
                project_id=project_id,
                name=job.name.strip()[:160],
                original_filename=f"{job.name.strip()[:80] or 'extraction'}.csv",
                file_type="csv",
                file_size_bytes=len(csv_bytes),
                current_user=current_user,
                pipeline_run_id=run.id,
            )

        relative_path, _ = build_derived_dataset_path(
            project_id=str(project_id),
            dataset_id=str(dataset.id),
            basename="extracted.csv",
        )
        try:
            stored = storage_backend.save_upload(relative_path=relative_path, file_bytes=csv_bytes)
        except OSError as exc:
            if dataset.id != previous_dataset_id:
                db.delete(dataset)
                db.flush()
            raise BadRequestError(f"Unable to store extracted file: {exc}") from exc

        dataset_detail = finalize_dataset_materialization_success(
            db,
            dataset=dataset,
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

        # Advance incremental state only after the artifact is safely persisted,
        # so a failed write cannot skip rows on the next run.
        new_watermark = job.watermark_value
        if job.load_mode != "full_refresh":
            if sources.is_sql(connection.connector_type):
                batch_watermark = compute_watermark(incoming, job.cursor_column) if job.cursor_column else None
            else:
                batch_watermark = connector_cursor
            if batch_watermark is not None:
                new_watermark = batch_watermark
                job.watermark_value = batch_watermark
                job.watermark_updated_at = datetime.now(UTC)

        if drift_report is not None and drift_report.has_drift:
            record_drift_event(
                db,
                project_id=project_id,
                dataset_id=dataset_detail.id,
                previous_dataset_id=previous_dataset_id,
                report=drift_report,
                extraction_job_id=job.id,
            )

        job.target_dataset_id = dataset_detail.id
        job.last_run_at = datetime.now(UTC)
        job.last_run_status = "succeeded"
        job.last_row_count = int(len(working))
        job.last_error_message = None
        job.execution_count = int(job.execution_count or 0) + 1

        summary_json: dict[str, Any] = {
            "extraction_type": RUN_TYPE,
            "job": {"id": str(job.id), "name": job.name},
            "connection": {"id": str(connection.id), "name": connection.name, "type": connection.connector_type},
            "load_mode": job.load_mode,
            "rows_extracted": result.row_count,
            "rows_added": merged.rows_added,
            "rows_updated": merged.rows_updated,
            "rows_before": merged.rows_before,
            "total_rows": int(len(working)),
            "column_count": int(len(working.columns)),
            "watermark_value": new_watermark,
            "truncated": result.truncated,
            "dataset": {"id": str(dataset_detail.id), "name": dataset_detail.name},
            "warnings": warnings,
            # Where the job's steps ran, when it has any: what the source did
            # as SQL, what ran here, and why -- the plan is a record, not a promise.
            "shaping": shaping_plan,
        }

        log_events.append(_log_event("succeeded", "Finished."))
        run_read = mark_pipeline_run_succeeded(
            db, run=run, summary_json=summary_json, logs_json={"events": log_events}
        )
        db.commit()
        db.refresh(job)

        return ExtractionRunResponse(
            job=ExtractionJobRead.model_validate(job, from_attributes=True),
            dataset_id=dataset_detail.id,
            run_id=run_read.id,
            rows_extracted=result.row_count,
            rows_added=merged.rows_added,
            rows_updated=merged.rows_updated,
            total_rows=int(len(working)),
            load_mode=job.load_mode,
            watermark_value=new_watermark,
            truncated=result.truncated,
            warnings=warnings,
            shaping=shaping_plan,
        )

    except ApplicationError as exc:
        _record_failure(db, job=job, run=run, log_events=log_events, stage=current_stage, message=exc.detail)
        raise
    except Exception as exc:
        logger.exception(
            "extraction_run_unexpected_error project_id=%s job_id=%s stage=%s", project_id, job_id, current_stage
        )
        _record_failure(
            db,
            job=job,
            run=run,
            log_events=log_events,
            stage=current_stage,
            message="The import stopped with an unexpected error.",
        )
        raise InternalServerError("The import stopped with an unexpected error. Try again; if it repeats, check the source connection.") from exc


def _record_failure(
    db: Session,
    *,
    job: ExtractionJob,
    run: Any,
    log_events: list[dict[str, Any]],
    stage: str,
    message: str,
) -> None:
    log_events.append(
        _log_event("failed", f"Stopped while {_stage_words(stage)}.", details={"error": message, "failure_stage": stage})
    )
    job.last_run_at = datetime.now(UTC)
    job.last_run_status = "failed"
    job.last_error_message = message[:2000]
    mark_pipeline_run_failed(
        db,
        run=run,
        summary_json={
            "extraction_type": RUN_TYPE,
            "job": {"id": str(job.id), "name": job.name},
            "failure_stage": stage,
            "error": message,
        },
        logs_json={"events": log_events},
    )
    db.commit()
