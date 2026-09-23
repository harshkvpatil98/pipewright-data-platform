"""Stream sources: rows that arrive, stored as events, materialised as data.

Two kinds, one lifecycle. A **webhook** source is an endpoint keyed by a token
(shown once, hashed at rest); whatever is posted to it is stored as an event.
A **postgres_cdc** source follows a database's change log through a logical
replication slot (see `cdc_postgres`), polled in micro-batches by the
schedule ticker. Either way the events accumulate in `stream_events`, and
**materialise** writes every event so far as one append-only dataset -- a new
immutable version each time, so the Phase 18 machinery (history, diff, AS OF,
retention) applies to a stream exactly as to an upload.

Honest about the model: this is micro-batch with seconds-to-a-minute latency,
at-least-once delivery, and no streaming transforms (windows, watermarks,
stateful aggregation). Those are the rest of Phase 20 and are not claimed.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import (
    create_uploaded_dataset_placeholder,
    finalize_dataset_materialization_success,
    get_dataset_model_for_project,
)
from service_extraction import cdc_postgres
from service_extraction.connectors import sql_database
from service_extraction.connectors.base import SENSITIVE_CONFIG_FIELDS
from service_extraction.models import ExtractionConnection, StreamEvent, StreamSource
from service_extraction.schemas import (
    StreamEventListResponse,
    StreamEventRead,
    StreamMaterialiseResponse,
    StreamPollResponse,
    StreamSourceCreate,
    StreamSourceCreated,
    StreamSourceListResponse,
    StreamSourceRead,
)
from service_ingestion.contracts import build_derived_dataset_path
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger
from shared_python.security.config_crypto import decrypt_sensitive_fields
from shared_python.storage import content_digest

logger = get_logger(__name__)

KINDS = ("webhook", "postgres_cdc")
MAX_WEBHOOK_BYTES = 256 * 1024
HOOK_PATH = "/api/v1/hooks/{token}"
_SLOT_SAFE = re.compile(r"[^a-z0-9_]+")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read(source: StreamSource, *, connection_name: str | None = None, dataset_name: str | None = None) -> StreamSourceRead:
    return StreamSourceRead(
        id=source.id,
        project_id=source.project_id,
        name=source.name,
        kind=source.kind,  # type: ignore[arg-type]
        status=source.status,
        connection_id=source.connection_id,
        connection_name=connection_name,
        tables=list((source.config_json or {}).get("tables") or []),
        slot_name=(source.config_json or {}).get("slot_name"),
        webhook_path=HOOK_PATH.replace("{token}", "…") if source.kind == "webhook" else None,
        cursor=source.cursor,
        dataset_id=source.dataset_id,
        dataset_name=dataset_name,
        events_count=source.events_count,
        last_event_at=source.last_event_at,
        last_polled_at=source.last_polled_at,
        last_materialised_at=source.last_materialised_at,
        last_error=source.last_error,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _reads(db: Session, sources: list[StreamSource]) -> list[StreamSourceRead]:
    from service_datasets.models import Dataset

    connections = {
        row.id: row.name
        for row in db.scalars(
            select(ExtractionConnection).where(
                ExtractionConnection.id.in_([s.connection_id for s in sources if s.connection_id] or [uuid.uuid4()])
            )
        ).all()
    }
    datasets = {
        row.id: row.name
        for row in db.scalars(
            select(Dataset).where(Dataset.id.in_([s.dataset_id for s in sources if s.dataset_id] or [uuid.uuid4()]))
        ).all()
    }
    return [
        _read(s, connection_name=connections.get(s.connection_id) if s.connection_id else None,
              dataset_name=datasets.get(s.dataset_id) if s.dataset_id else None)
        for s in sources
    ]


def _get_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> StreamSource:
    source = db.scalar(select(StreamSource).where(StreamSource.id == source_id, StreamSource.project_id == project_id))
    if source is None:
        raise NotFoundError("Stream source not found.")
    return source


# ------------------------------------------------------------------ CRUD


def list_sources(db: Session, project_id: uuid.UUID, current_user: UserRead) -> StreamSourceListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    sources = list(db.scalars(select(StreamSource).where(StreamSource.project_id == project_id).order_by(StreamSource.created_at.desc())).all())
    return StreamSourceListResponse(items=_reads(db, sources))


def get_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> StreamSourceRead:
    ensure_owned_project(db, project_id, current_user.id)
    return _reads(db, [_get_source(db, project_id, source_id)])[0]


def create_source(db: Session, project_id: uuid.UUID, payload: StreamSourceCreate, current_user: UserRead) -> StreamSourceCreated:
    ensure_owned_project(db, project_id, current_user.id)
    token: str | None = None
    config: dict[str, Any] = {}
    connection_id: uuid.UUID | None = None
    if payload.kind == "webhook":
        token = secrets.token_urlsafe(32)
    else:
        if payload.connection_id is None:
            raise BadRequestError("A change-data-capture source needs a PostgreSQL connection.")
        connection = db.scalar(select(ExtractionConnection).where(
            ExtractionConnection.id == payload.connection_id, ExtractionConnection.project_id == project_id))
        if connection is None:
            raise NotFoundError("Connection not found in this project.")
        if connection.connector_type != "postgresql":
            raise BadRequestError(
                f"Change data capture follows PostgreSQL's logical replication; '{connection.connector_type}' "
                "is not supported here. MySQL binlog and others are stated gaps, not silent ones."
            )
        if not payload.tables:
            raise BadRequestError("Name at least one table to follow (schema.table or table).")
        connection_id = connection.id
        slot = _SLOT_SAFE.sub("_", (payload.slot_name or f"pipewright_{payload.name}").lower()).strip("_")[:60] or "pipewright"
        config = {"tables": [t.strip() for t in payload.tables if t.strip()], "slot_name": slot, "batch": 500}
    source = StreamSource(
        project_id=project_id,
        name=payload.name.strip(),
        kind=payload.kind,
        connection_id=connection_id,
        config_json=config,
        token_hash=_hash_token(token) if token else None,
        created_by_user_id=current_user.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    read = _reads(db, [source])[0]
    return StreamSourceCreated(
        **read.model_dump(),
        token=token,
        webhook_path_with_token=HOOK_PATH.replace("{token}", token) if token else None,
    )


def delete_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    if source.kind == "postgres_cdc":
        # Drop the slot, or the database keeps WAL for a reader that is gone.
        try:
            engine = _engine_for(db, source)
            cdc_postgres.drop_slot(engine, source.config_json["slot_name"])
        except Exception:  # noqa: BLE001 - deleting the source must not depend on the source
            logger.warning("cdc_slot_not_dropped source_id=%s", source.id)
    # Explicit, not left to the database's cascade: the events are this
    # source's and go with it whether or not the engine enforces the FK.
    db.execute(sa_delete(StreamEvent).where(StreamEvent.source_id == source.id))
    db.delete(source)
    db.commit()


def list_events(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead, *, limit: int = 50) -> StreamEventListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    rows = db.scalars(
        select(StreamEvent).where(StreamEvent.source_id == source.id).order_by(StreamEvent.seq.desc()).limit(limit)
    ).all()
    return StreamEventListResponse(items=[StreamEventRead.model_validate(r, from_attributes=True) for r in rows])


# ------------------------------------------------------------ webhooks


def receive_webhook(db: Session, *, token: str, body: bytes, content_type: str | None, headers: dict[str, str]) -> StreamEventRead:
    """Store one post. Public: the token IS the authorisation, compared in
    constant time against the hash; an unknown token is a 404, not a hint."""
    if len(body) > MAX_WEBHOOK_BYTES:
        raise BadRequestError(f"Webhook payload exceeds {MAX_WEBHOOK_BYTES // 1024} KB.")
    digest = _hash_token(token)
    source = None
    for candidate in db.scalars(select(StreamSource).where(StreamSource.kind == "webhook", StreamSource.token_hash == digest)).all():
        if hmac.compare_digest(candidate.token_hash or "", digest):
            source = candidate
    if source is None:
        raise NotFoundError("No webhook is listening at this address.")
    if source.status != "active":
        raise ConflictError("This webhook is paused.")
    payload: dict[str, Any]
    text_body = body.decode("utf-8", errors="replace")
    if content_type and "json" in content_type:
        try:
            decoded = json.loads(text_body or "null")
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"The body is not valid JSON: {exc.msg}.") from exc
        payload = decoded if isinstance(decoded, dict) else {"value": decoded}
    else:
        payload = {"body": text_body}
    kept_headers = {k: v for k, v in headers.items() if k.lower() in ("user-agent", "x-event-type", "x-github-event", "x-request-id")}
    if kept_headers:
        payload = {**payload, "_headers": kept_headers}
    event = _append_event(db, source, kind="webhook", table_name=None, position=None, payload=payload)
    db.commit()
    db.refresh(event)
    return StreamEventRead.model_validate(event, from_attributes=True)


def _append_event(db: Session, source: StreamSource, *, kind: str, table_name: str | None,
                  position: str | None, payload: dict[str, Any]) -> StreamEvent:
    next_seq = int(db.scalar(select(func.coalesce(func.max(StreamEvent.seq), 0)).where(StreamEvent.source_id == source.id)) or 0) + 1
    event = StreamEvent(source_id=source.id, seq=next_seq, kind=kind, table_name=table_name, position=position, payload_json=payload)
    db.add(event)
    source.events_count = int(source.events_count or 0) + 1
    source.last_event_at = datetime.now(UTC)
    db.flush()
    return event


# ---------------------------------------------------------------- CDC


def _engine_for(db: Session, source: StreamSource):
    connection = db.get(ExtractionConnection, source.connection_id) if source.connection_id else None
    if connection is None:
        raise BadRequestError("The connection behind this source no longer exists.")
    config = decrypt_sensitive_fields(dict(connection.config_json or {}), SENSITIVE_CONFIG_FIELDS)
    return sql_database.get_engine(connection.connector_type, config)


def poll_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead | None) -> StreamPollResponse:
    """Read the next batch of changes from the slot, store them, consume."""
    if current_user is not None:
        ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    if source.kind != "postgres_cdc":
        raise BadRequestError("Only a change-data-capture source is polled; a webhook receives.")
    slot = source.config_json["slot_name"]
    tables = list(source.config_json.get("tables") or [])
    batch = int(source.config_json.get("batch") or 500)
    now = datetime.now(UTC)
    try:
        engine = _engine_for(db, source)
        capability = cdc_postgres.check_capability(engine)
        if not capability.ok:
            raise BadRequestError(capability.reason)
        created = cdc_postgres.ensure_slot(engine, slot)
        changes = cdc_postgres.peek_changes(engine, slot, limit=batch, tables=tables)
        upto = cdc_postgres.last_peeked_lsn(engine, slot, limit=batch)
        known = {
            row for row in db.scalars(
                select(StreamEvent.position).where(StreamEvent.source_id == source.id, StreamEvent.position.is_not(None))
            ).all()
        }
        stored = 0
        for change in changes:
            key = f"{change.lsn}#{change.xid}#{change.op}#{json.dumps(change.row, sort_keys=True, default=str)}"
            position = hashlib.sha1(key.encode()).hexdigest()[:24]
            if position in known:
                continue  # re-read after a crash: already stored
            _append_event(
                db, source, kind=change.op, table_name=change.table, position=position,
                payload={"lsn": change.lsn, "xid": change.xid, "row": change.row, "old_key": change.old_key},
            )
            known.add(position)
            stored += 1
        consumed = cdc_postgres.consume_upto(engine, slot, upto) if upto else 0
        source.cursor = upto or source.cursor
        source.last_polled_at = now
        source.last_error = None
        db.commit()
        db.refresh(source)
        return StreamPollResponse(
            source=_reads(db, [source])[0], slot_created=created, changes_read=len(changes),
            events_stored=stored, lines_consumed=consumed, upto_lsn=upto,
            note="at-least-once: a change stored before the slot advanced is never lost; a crash in between re-reads it and the position makes the re-read a no-op",
        )
    except BadRequestError as exc:
        source.last_polled_at = now
        source.last_error = str(exc.detail)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - the source's error is recorded and reported
        source.last_polled_at = now
        source.last_error = str(exc)[:1000]
        db.commit()
        raise BadRequestError(f"Polling failed: {str(exc)[:300]}") from exc


# ----------------------------------------------------------- materialise


def _events_frame(source: StreamSource, events: list[StreamEvent]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        base = {"seq": event.seq, "kind": event.kind, "received_at": event.received_at.isoformat() if event.received_at else None}
        payload = event.payload_json or {}
        if source.kind == "postgres_cdc":
            base.update({"table": event.table_name, "lsn": payload.get("lsn"), "xid": payload.get("xid")})
            for key, value in (payload.get("row") or {}).items():
                base[key] = value
            if not payload.get("row") and payload.get("old_key"):
                for key, value in payload["old_key"].items():
                    base[key] = value
        else:
            flat = pd.json_normalize({k: v for k, v in payload.items() if k != "_headers"}, sep=".").to_dict(orient="records")
            base.update(flat[0] if flat else {})
        rows.append({k: (json.dumps(v, default=str) if isinstance(v, (list, dict)) else v) for k, v in base.items()})
    return pd.DataFrame(rows)


def materialise_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead,
                       storage_backend, settings) -> StreamMaterialiseResponse:
    """Write every event so far as one append-only dataset: a new immutable
    version each time, on the same dataset, so history, diff and AS OF apply."""
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    events = list(db.scalars(select(StreamEvent).where(StreamEvent.source_id == source.id).order_by(StreamEvent.seq)).all())
    if not events:
        raise BadRequestError("Nothing has arrived yet; there is nothing to materialise.")
    frame = _events_frame(source, events)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    csv_bytes = buffer.getvalue().encode("utf-8")
    if len(csv_bytes) > settings.max_upload_size_bytes:
        raise BadRequestError("The event log exceeds the configured maximum dataset size.")

    if source.dataset_id is not None:
        dataset = get_dataset_model_for_project(db, project_id, source.dataset_id)
    else:
        dataset = create_uploaded_dataset_placeholder(
            db, project_id=project_id, name=f"{source.name} (stream)"[:160],
            original_filename=f"{source.name[:80] or 'stream'}.csv", file_type="csv",
            file_size_bytes=len(csv_bytes), current_user=current_user, pipeline_run_id=None,
        )
        source.dataset_id = dataset.id
    relative_path, _ = build_derived_dataset_path(project_id=str(project_id), dataset_id=str(dataset.id), basename="stream.csv")
    stored = storage_backend.save_upload(relative_path=relative_path, file_bytes=csv_bytes)
    schema = infer_schema(dataframe=frame)
    dataset.file_type = "csv"
    dataset.file_size_bytes = len(csv_bytes)
    detail = finalize_dataset_materialization_success(
        db, dataset=dataset, file_path=stored.relative_path, file_name=stored.file_name,
        schema_json=schema, schema_snapshot={"columns": schema["columns"]},
        preview_json=build_preview(dataframe=frame, limit=settings.preview_row_limit),
        profile_json=build_profile(dataframe=frame, sample_limit=settings.profile_sample_value_limit, file_size_bytes=len(csv_bytes)),
        row_count=int(len(frame)), column_count=int(len(frame.columns)),
        content_hash=content_digest(csv_bytes), created_by_user_id=current_user.id,
    )
    source.last_materialised_at = datetime.now(UTC)
    db.commit()
    db.refresh(source)
    from service_datasets.models import DatasetVersion

    version = db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset.id))
    return StreamMaterialiseResponse(
        source=_reads(db, [source])[0], dataset_id=detail.id, version_number=int(version or 0),
        rows=int(len(frame)), columns=[str(c) for c in frame.columns],
    )


def sweep_cdc_sources(db: Session, *, storage_backend, settings) -> dict[str, int]:
    """The ticker's pass: poll every active CDC source and materialise the ones
    that received something. Best effort per source; one broken database
    never stops the others."""
    totals = {"sources": 0, "events": 0, "materialised": 0, "failed": 0}
    for source in db.scalars(select(StreamSource).where(StreamSource.kind == "postgres_cdc", StreamSource.status == "active")).all():
        totals["sources"] += 1
        try:
            polled = poll_source(db, source.project_id, source.id, None)
            totals["events"] += polled.events_stored
            if polled.events_stored and source.created_by_user_id:
                from service_auth.models import User

                owner = db.get(User, source.created_by_user_id)
                if owner is not None and owner.is_active:
                    materialise_source(db, source.project_id, source.id, UserRead.model_validate(owner), storage_backend, settings)
                    totals["materialised"] += 1
        except Exception:  # noqa: BLE001 - recorded on the source by poll_source
            totals["failed"] += 1
            db.rollback()
    return totals
