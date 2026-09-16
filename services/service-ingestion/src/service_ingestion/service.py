from __future__ import annotations

import uuid
from datetime import UTC, datetime

from service_auth.schemas import UserRead
from service_datasets.service import (
    create_uploaded_dataset_placeholder,
    finalize_dataset_ingestion_failure,
    finalize_dataset_ingestion_success,
    mark_dataset_ingestion_running,
)
from service_ingestion.contracts import build_upload_path, validate_upload_file
from service_ingestion.parsers import parse_tabular_file
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_ingestion.schemas import DatasetUploadResponse, IngestionUpload
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import ApplicationError, BadRequestError, InternalServerError
from shared_python.logging import get_logger

logger = get_logger(__name__)


def _log_event(stage: str, message: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
    event: dict[str, object] = {
        'stage': stage,
        'message': message,
        'recorded_at': datetime.now(UTC).isoformat(),
    }
    if details:
        event['details'] = details
    return event


def _build_log_events(events: list[dict[str, object]]) -> dict[str, object]:
    return {'events': events}


def _profile_for(*, parsed, file_bytes: bytes, settings, log_events: list) -> dict:
    """Profile the file, streaming it when it is too big to hold twice.

    Below the threshold the frame is already in memory and profiling it is
    free. Above it, the file is re-read a chunk at a time and the statistics
    are accumulated -- which is slower and is the only way a 2GB CSV profiles
    at all. The profile says which of the two it was.
    """
    from service_ingestion import streaming

    streamable = parsed.metadata.get('format') in ('csv', 'tsv', 'psv')
    if not (streaming.should_stream(len(file_bytes)) and streamable):
        return build_profile(
            dataframe=parsed.dataframe,
            sample_limit=settings.profile_sample_value_limit,
            file_size_bytes=len(file_bytes),
        )

    log_events.append(
        _log_event(
            'profile',
            'File is large; profiling by streaming it rather than holding it in memory.',
            details={'file_size_bytes': len(file_bytes)},
        )
    )
    return streaming.profile_stream(
        streaming.chunks_of_delimited(file_bytes, options=parsed.spec.get('options') or {}),
        file_size_bytes=len(file_bytes),
    )


def ingest_project_file(
    db,
    *,
    project_id: uuid.UUID,
    dataset_name: str | None,
    upload_file: IngestionUpload,
    storage_backend,
    settings,
    current_user: UserRead,
    ingest_spec: dict | None = None,
) -> DatasetUploadResponse:
    project = ensure_owned_project(db, project_id, current_user.id)
    file_type = validate_upload_file(upload_file, settings)
    file_bytes = upload_file.file_bytes
    log_events = [
        _log_event(
            'queued',
            'Ingestion request accepted by the gateway.',
            details={
                'project_id': str(project.id),
                'dataset_name': dataset_name.strip() if dataset_name and dataset_name.strip() else None,
                'original_filename': upload_file.file_name,
                'file_type': file_type,
                'file_size_bytes': len(file_bytes),
            },
        )
    ]
    current_stage = 'queued'

    if not file_bytes:
        raise BadRequestError('Uploaded file is empty.')
    if len(file_bytes) > settings.max_upload_size_bytes:
        raise BadRequestError('Uploaded file exceeds the configured maximum size.')

    pipeline_run = create_pipeline_run(
        db,
        project_id=project.id,
        current_user=current_user,
        run_type='dataset_ingestion',
        logs_json=_build_log_events(log_events),
    )

    dataset_name = (
        dataset_name.strip()
        if dataset_name and dataset_name.strip()
        else upload_file.file_name.rsplit('.', 1)[0] if upload_file.file_name else 'uploaded-dataset'
    )
    dataset = create_uploaded_dataset_placeholder(
        db,
        project_id=project.id,
        name=dataset_name,
        original_filename=upload_file.file_name,
        file_type=file_type,
        file_size_bytes=len(file_bytes),
        current_user=current_user,
        pipeline_run_id=pipeline_run.id,
    )

    relative_path, _ = build_upload_path(
        project_id=str(project.id),
        dataset_id=str(dataset.id),
        original_filename=upload_file.file_name,
    )

    try:
        # The request performs ingestion synchronously today, but this lifecycle mirrors a future
        # background worker so runs and datasets already expose durable queued/running terminal states.
        current_stage = 'running'
        log_events.append(_log_event('running', 'Preparing storage and parsing pipeline.'))
        mark_pipeline_run_running(
            db,
            run=pipeline_run,
            logs_json=_build_log_events(log_events),
        )
        mark_dataset_ingestion_running(db, dataset=dataset)

        current_stage = 'upload'
        log_events.append(_log_event('upload', 'Saving uploaded file to configured storage.'))
        stored_artifact = storage_backend.save_upload(relative_path=relative_path, file_bytes=file_bytes)

        log_events.append(
            _log_event(
                'upload',
                'Uploaded file stored successfully.',
                details={
                    'stored_file_name': stored_artifact.file_name,
                    'stored_file_size_bytes': stored_artifact.size_bytes,
                },
            )
        )

        current_stage = 'parse'
        parsed = parse_tabular_file(
            file_bytes=file_bytes,
            file_type=file_type,
            file_name=upload_file.file_name,
            content_type=upload_file.content_type,
            ingest_spec=ingest_spec,
        )
        log_events.append(
            _log_event(
                'parse',
                'File parsed into a tabular structure.',
                details=parsed.metadata,
            )
        )
        for warning in parsed.warnings:
            log_events.append(_log_event('parse', warning))

        current_stage = 'profile'
        schema_json = infer_schema(dataframe=parsed.dataframe)
        preview_json = build_preview(dataframe=parsed.dataframe, limit=settings.preview_row_limit)
        profile_json = _profile_for(
            parsed=parsed,
            file_bytes=file_bytes,
            settings=settings,
            log_events=log_events,
        )
        log_events.append(
            _log_event(
                'profile',
                'Schema, preview, and profile metrics generated.',
                details={
                    'row_count': profile_json['row_count'],
                    'column_count': profile_json['column_count'],
                    'preview_row_count': len(preview_json['rows']),
                },
            )
        )

        current_stage = 'persist'
        dataset_detail = finalize_dataset_ingestion_success(
            db,
            dataset=dataset,
            file_path=stored_artifact.relative_path,
            file_name=stored_artifact.file_name,
            schema_json=schema_json,
            schema_snapshot={'columns': schema_json['columns']},
            preview_json=preview_json,
            profile_json=profile_json,
            row_count=profile_json['row_count'],
            column_count=profile_json['column_count'],
            ingest_spec_json=parsed.spec,
        )
        log_events.append(
            _log_event(
                'persist',
                'Dataset artifact state persisted successfully.',
                details={
                    'dataset_id': str(dataset.id),
                    'pipeline_run_id': str(pipeline_run.id),
                },
            )
        )
        log_events.append(_log_event('succeeded', 'Dataset ingestion completed successfully.'))
        run_detail = mark_pipeline_run_succeeded(
            db,
            run=pipeline_run,
            summary_json={
                'ingestion_type': 'dataset_upload',
                'dataset': {
                    'id': str(dataset.id),
                    'name': dataset.name,
                    'ingestion_status': dataset_detail.ingestion_status,
                    'row_count': profile_json['row_count'],
                    'column_count': profile_json['column_count'],
                },
                'artifact': {
                    'original_filename': upload_file.file_name,
                    'stored_file_name': stored_artifact.file_name,
                    'file_type': file_type,
                    'file_size_bytes': len(file_bytes),
                },
                'profile': {
                    'duplicate_row_count': profile_json['duplicate_row_count'],
                    'duplicate_row_percentage': profile_json['duplicate_row_percentage'],
                    'completeness_score': profile_json['completeness_score'],
                },
                'parser_metadata': parsed.metadata,
            },
            logs_json=_build_log_events(log_events),
        )
        return DatasetUploadResponse(dataset=dataset_detail, run=run_detail)
    except ApplicationError as exc:
        logger.warning(
            'dataset_ingestion_application_error project_id=%s dataset_id=%s file_type=%s stage=%s detail=%s',
            project.id,
            dataset.id,
            file_type,
            current_stage,
            exc.detail,
        )
        safe_error = exc.detail
        log_events.append(
            _log_event(
                'failed',
                f'Ingestion failed during {current_stage}.',
                details={'error': safe_error, 'failure_stage': current_stage},
            )
        )
        dataset_detail = finalize_dataset_ingestion_failure(db, dataset=dataset, ingestion_error=safe_error)
        mark_pipeline_run_failed(
            db,
            run=pipeline_run,
            summary_json={
                'ingestion_type': 'dataset_upload',
                'failure_stage': current_stage,
                'dataset': {
                    'id': str(dataset.id),
                    'name': dataset.name,
                    'ingestion_status': dataset_detail.ingestion_status,
                },
                'artifact': {
                    'original_filename': upload_file.file_name,
                    'file_type': file_type,
                    'file_size_bytes': len(file_bytes),
                },
                'error': safe_error,
            },
            logs_json=_build_log_events(log_events),
        )
        if storage_backend.exists(relative_path):
            storage_backend.delete(relative_path)
        raise BadRequestError(dataset_detail.ingestion_error or 'Ingestion failed.') from exc
    except Exception as exc:
        logger.exception(
            'dataset_ingestion_unexpected_error project_id=%s dataset_id=%s file_type=%s stage=%s',
            project.id,
            dataset.id,
            file_type,
            current_stage,
        )
        safe_error = 'Dataset ingestion failed due to an internal processing error.'
        log_events.append(
            _log_event(
                'failed',
                f'Ingestion failed during {current_stage}.',
                details={'error': safe_error, 'failure_stage': current_stage},
            )
        )
        finalize_dataset_ingestion_failure(db, dataset=dataset, ingestion_error=safe_error)
        mark_pipeline_run_failed(
            db,
            run=pipeline_run,
            summary_json={
                'ingestion_type': 'dataset_upload',
                'failure_stage': current_stage,
                'dataset': {
                    'id': str(dataset.id),
                    'name': dataset.name,
                    'ingestion_status': 'failed',
                },
                'artifact': {
                    'original_filename': upload_file.file_name,
                    'file_type': file_type,
                    'file_size_bytes': len(file_bytes),
                },
                'error': safe_error,
            },
            logs_json=_build_log_events(log_events),
        )
        if storage_backend.exists(relative_path):
            storage_backend.delete(relative_path)
        raise InternalServerError(safe_error) from exc
