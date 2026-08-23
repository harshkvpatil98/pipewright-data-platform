"""Connection and job management for database extraction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_extraction.connectors import sql_database
from service_extraction.connectors.base import SENSITIVE_CONFIG_FIELDS
from service_extraction.models import ExtractionConnection, ExtractionJob
from service_extraction.schemas import (
    ConnectionTestResponse,
    DiscoveredColumnRead,
    DiscoveredColumnsResponse,
    DiscoveredTable,
    DiscoveredTablesResponse,
    ExtractionConnectionCreate,
    ExtractionConnectionListResponse,
    ExtractionConnectionRead,
    ExtractionConnectionUpdate,
    ExtractionJobCreate,
    ExtractionJobListResponse,
    ExtractionJobRead,
    ExtractionJobUpdate,
    ExtractionPreviewRequest,
    ExtractionPreviewResponse,
)
from service_extraction.sql_safety import ensure_read_only_select
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.security.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields

REQUIRED_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "postgresql": ("host", "database", "username"),
    "mysql": ("host", "database", "username"),
    "sqlite": ("file_path",),
}

_REDACTED = "***"


def _redact(config: dict[str, Any]) -> dict[str, Any]:
    """Mask secrets so a stored config can be safely returned by the API."""
    out = dict(config)
    for key in SENSITIVE_CONFIG_FIELDS:
        if out.get(key):
            out[key] = _REDACTED
    return out


def _to_read(connection: ExtractionConnection) -> ExtractionConnectionRead:
    data = ExtractionConnectionRead.model_validate(connection, from_attributes=True)
    return data.model_copy(update={"config_json": _redact(dict(connection.config_json or {}))})


def _validate_config(connector_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise BadRequestError("Connection config must be an object.")

    missing = [field for field in REQUIRED_CONFIG_FIELDS[connector_type] if not str(config.get(field, "")).strip()]
    if missing:
        raise BadRequestError(
            f"Connection config for {connector_type} is missing: {', '.join(sorted(missing))}."
        )
    # Fail fast on a malformed host/port rather than at first use.
    sql_database.build_url(connector_type, config)
    return config


def _decrypted_config(connection: ExtractionConnection) -> dict[str, Any]:
    return decrypt_sensitive_fields(dict(connection.config_json or {}), SENSITIVE_CONFIG_FIELDS)


def get_connection_for_project(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID
) -> ExtractionConnection:
    connection = db.scalar(
        select(ExtractionConnection).where(
            ExtractionConnection.id == connection_id,
            ExtractionConnection.project_id == project_id,
        )
    )
    if connection is None:
        raise NotFoundError("Extraction connection not found.")
    return connection


def list_connections(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> ExtractionConnectionListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(ExtractionConnection)
        .where(ExtractionConnection.project_id == project_id)
        .order_by(ExtractionConnection.created_at.desc())
    ).all()
    return ExtractionConnectionListResponse(items=[_to_read(row) for row in rows])


def create_connection(
    db: Session,
    project_id: uuid.UUID,
    payload: ExtractionConnectionCreate,
    current_user: UserRead,
) -> ExtractionConnectionRead:
    ensure_owned_project(db, project_id, current_user.id)
    config = _validate_config(payload.connector_type, dict(payload.config))

    connection = ExtractionConnection(
        project_id=project_id,
        name=payload.name.strip(),
        connector_type=payload.connector_type,
        description=payload.description,
        status="active",
        config_json=encrypt_sensitive_fields(config, SENSITIVE_CONFIG_FIELDS),
        created_by_user_id=current_user.id,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _to_read(connection)


def update_connection(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: ExtractionConnectionUpdate,
    current_user: UserRead,
) -> ExtractionConnectionRead:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)

    if payload.name is not None:
        connection.name = payload.name.strip()
    if payload.description is not None:
        connection.description = payload.description
    if payload.status is not None:
        connection.status = payload.status
    if payload.config is not None:
        incoming = dict(payload.config)
        stored = dict(connection.config_json or {})
        # An omitted, blank, or still-redacted secret means "leave it alone", so the
        # stored ciphertext is carried forward instead of being wiped.
        for key in SENSITIVE_CONFIG_FIELDS:
            if incoming.get(key) in (None, "", _REDACTED):
                incoming.pop(key, None)
                if stored.get(key):
                    incoming[key] = stored[key]
        # decrypt/encrypt are both pass-through when the value is already in the
        # target form, so this normalises a mix of ciphertext and new plaintext.
        plain = decrypt_sensitive_fields(incoming, SENSITIVE_CONFIG_FIELDS)
        _validate_config(connection.connector_type, plain)
        connection.config_json = encrypt_sensitive_fields(plain, SENSITIVE_CONFIG_FIELDS)

    db.commit()
    db.refresh(connection)
    return _to_read(connection)


def delete_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)
    db.delete(connection)
    db.commit()


def test_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> ConnectionTestResponse:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)

    result = sql_database.test_connection(connection.connector_type, _decrypted_config(connection))

    connection.last_tested_at = datetime.now(UTC)
    connection.last_test_status = "succeeded" if result.success else "failed"
    connection.last_test_message = result.message[:2000]
    db.commit()

    return ConnectionTestResponse(
        success=result.success,
        message=result.message,
        latency_ms=result.latency_ms,
        server_version=result.server_version,
        warnings=list(result.warnings),
    )


def discover_tables(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> DiscoveredTablesResponse:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)
    tables = sql_database.list_tables(connection.connector_type, _decrypted_config(connection))
    return DiscoveredTablesResponse(
        items=[
            DiscoveredTable(
                schema_name=ref.schema,
                name=ref.name,
                kind=ref.kind,
                qualified_name=ref.qualified_name,
            )
            for ref in tables
        ]
    )


def discover_columns(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    table: str,
    schema: str | None,
    current_user: UserRead,
) -> DiscoveredColumnsResponse:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)
    columns = sql_database.list_columns(
        connection.connector_type, _decrypted_config(connection), table=table, schema=schema
    )
    return DiscoveredColumnsResponse(
        table=table,
        schema_name=schema,
        items=[
            DiscoveredColumnRead(
                name=column.name,
                data_type=column.data_type,
                nullable=column.nullable,
                primary_key=column.primary_key,
            )
            for column in columns
        ],
    )


def resolve_job_query(connector_type: str, *, source_kind: str, table: str | None, schema: str | None, query_sql: str | None) -> str:
    """Produce the read-only SELECT for a job or preview request."""
    if source_kind == "query":
        return ensure_read_only_select(query_sql or "")
    if not table:
        raise BadRequestError("A table name is required for table extraction.")
    return sql_database.build_table_query(connector_type, table=table, schema=schema)


def preview_extraction(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: ExtractionPreviewRequest,
    current_user: UserRead,
) -> ExtractionPreviewResponse:
    """Run a bounded read so operators can see shape before saving a job."""
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)
    config = _decrypted_config(connection)

    statement = resolve_job_query(
        connection.connector_type,
        source_kind=payload.source_kind,
        table=payload.table,
        schema=payload.schema_name,
        query_sql=payload.query_sql,
    )

    result = sql_database.read_dataframe(
        connection.connector_type,
        config,
        sql=statement,
        max_rows=payload.limit,
        chunk_size=payload.limit,
    )
    frame = result.dataframe

    from service_transformations.tabular import json_preview_rows  # local import avoids a package cycle

    return ExtractionPreviewResponse(
        columns=[str(column) for column in frame.columns],
        rows=json_preview_rows(frame, payload.limit),
        row_count=result.row_count,
        truncated=result.truncated,
        warnings=list(result.warnings),
    )


# --------------------------------------------------------------------------- jobs


def get_job_for_project(db: Session, project_id: uuid.UUID, job_id: uuid.UUID) -> ExtractionJob:
    job = db.scalar(
        select(ExtractionJob).where(ExtractionJob.id == job_id, ExtractionJob.project_id == project_id)
    )
    if job is None:
        raise NotFoundError("Extraction job not found.")
    return job


def list_jobs(db: Session, project_id: uuid.UUID, current_user: UserRead) -> ExtractionJobListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(ExtractionJob)
        .where(ExtractionJob.project_id == project_id)
        .order_by(ExtractionJob.created_at.desc())
    ).all()
    return ExtractionJobListResponse(items=[ExtractionJobRead.model_validate(row, from_attributes=True) for row in rows])


def create_job(
    db: Session, project_id: uuid.UUID, payload: ExtractionJobCreate, current_user: UserRead
) -> ExtractionJobRead:
    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, payload.connection_id)

    # Validate the query now so a broken job cannot be saved and later scheduled.
    resolve_job_query(
        connection.connector_type,
        source_kind=payload.source_kind,
        table=payload.table,
        schema=payload.schema_name,
        query_sql=payload.query_sql,
    )

    job = ExtractionJob(
        project_id=project_id,
        connection_id=connection.id,
        name=payload.name.strip(),
        description=payload.description,
        source_kind=payload.source_kind,
        source_schema=payload.schema_name,
        source_table=payload.table,
        query_sql=payload.query_sql,
        load_mode=payload.load_mode,
        cursor_column=payload.cursor_column,
        primary_key_columns=list(payload.primary_key_columns),
        max_rows=payload.max_rows,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return ExtractionJobRead.model_validate(job, from_attributes=True)


def update_job(
    db: Session,
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: ExtractionJobUpdate,
    current_user: UserRead,
) -> ExtractionJobRead:
    ensure_owned_project(db, project_id, current_user.id)
    job = get_job_for_project(db, project_id, job_id)

    if payload.name is not None:
        job.name = payload.name.strip()
    if payload.description is not None:
        job.description = payload.description
    if payload.load_mode is not None:
        job.load_mode = payload.load_mode
    if payload.cursor_column is not None:
        job.cursor_column = payload.cursor_column
    if payload.primary_key_columns is not None:
        job.primary_key_columns = list(payload.primary_key_columns)
    if payload.max_rows is not None:
        job.max_rows = payload.max_rows
    if payload.enabled is not None:
        job.enabled = payload.enabled

    if job.load_mode != "full_refresh" and not (job.cursor_column or "").strip():
        raise BadRequestError("cursor_column is required for incremental load modes.")
    if job.load_mode == "incremental_merge" and not (job.primary_key_columns or []):
        raise BadRequestError("primary_key_columns is required for incremental_merge.")

    db.commit()
    db.refresh(job)
    return ExtractionJobRead.model_validate(job, from_attributes=True)


def delete_job(db: Session, project_id: uuid.UUID, job_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    job = get_job_for_project(db, project_id, job_id)
    db.delete(job)
    db.commit()


def reset_job_watermark(
    db: Session, project_id: uuid.UUID, job_id: uuid.UUID, current_user: UserRead
) -> ExtractionJobRead:
    """Clear incremental state so the next run re-reads from the beginning."""
    ensure_owned_project(db, project_id, current_user.id)
    job = get_job_for_project(db, project_id, job_id)
    job.watermark_value = None
    job.watermark_updated_at = None
    db.commit()
    db.refresh(job)
    return ExtractionJobRead.model_validate(job, from_attributes=True)


def total_extraction_connections(db: Session) -> int:
    return db.scalar(select(func.count(ExtractionConnection.id))) or 0


def total_extraction_jobs(db: Session) -> int:
    return db.scalar(select(func.count(ExtractionJob.id))) or 0
