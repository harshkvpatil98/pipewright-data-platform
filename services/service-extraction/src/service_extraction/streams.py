"""Live sources: rows that arrive, stored as events, kept as datasets (D1).

A live source is one of `live.KINDS`: a webhook, a database's change log or
a message queue. The runner (`api_gateway.scripts.live_runner`) reads each
active one every few seconds under a lease:

1. **Read** a batch from the saved position and store it in `stream_events`
   with the position the batch ends at, in one transaction; then acknowledge
   the batch to the source (or advance its replication slot). A batch that
   could not be stored is handed back. An event whose position is already
   stored is skipped, so a repeat delivery is saved once where the source gives
   it an id. A change-capture source first takes its position in the change
   log, then reads each followed table whole (the snapshot), so nothing that
   changes during the snapshot is missed.
2. **Process** live recipes (`live_recipes`): steps, lookups and windows.
3. **Save** every `save_every_seconds`: the log of every event (appended to
   the previous version, never rewritten from the start), each followed table
   as it is now (changes applied by key) and each live recipe's output. Each
   is a new immutable version of one dataset, so history, diff and AS OF apply
   to live data as to an upload, and each new version is checked against the
   dataset's contract first, as every producer's is (C1).

Events are kept `keep_events_hours` once every output has them; the log
dataset keeps the rest. Micro-batch: seconds of latency, never a held
connection.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import (
    create_uploaded_dataset_placeholder,
    finalize_dataset_materialization_success,
    get_dataset_model_for_project,
)
from service_extraction.connector_sources import secret_fields as connection_secret_fields
from service_extraction.live import KINDS, LiveError, get_kind
from service_extraction.live.base import ChangeCaptureKind, Message
from service_extraction.live.postgres import slot_name_for
from service_extraction.live.webhook import KEPT_HEADERS, idempotency_position
from service_extraction.models import ExtractionConnection, LiveRecipe, LiveTable, StreamEvent, StreamSource
from service_extraction.schemas import (
    LiveTableRead,
    LiveTestResult,
    StreamEventListResponse,
    StreamEventRead,
    StreamMaterialiseResponse,
    StreamPollResponse,
    StreamSourceCreate,
    StreamSourceCreated,
    StreamSourceListResponse,
    StreamSourceRead,
    StreamSourceUpdate,
    StreamTestRequest,
    ThroughputPoint,
)
from service_ingestion.contracts import build_derived_dataset_path
from service_ingestion.profiling import build_preview, build_profile, infer_schema
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger
from shared_python.security.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields
from shared_python.storage import content_digest
from shared_python.words import count_of

logger = get_logger(__name__)

KIND_KEYS = tuple(KINDS)
MAX_WEBHOOK_BYTES = 256 * 1024
HOOK_PATH = "/api/v1/hooks/{token}"
#: Events one read takes from a source.
READ_BATCH = 5_000
#: How long one pass keeps reading a source that has more waiting.
PASS_SECONDS = 20.0
#: Longest wait between tries for a source that keeps failing.
BACKOFF_LIMIT_SECONDS = 300
#: Failed passes in a row after which the owner is told, once.
NOTIFY_AFTER = 5
LEASE_SECONDS = 120
#: Rows a snapshot reads at a time.
SNAPSHOT_CHUNK = 5_000


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def cursor_of(source: StreamSource) -> dict[str, Any] | None:
    if not source.cursor:
        return None
    try:
        value = json.loads(source.cursor)
    except json.JSONDecodeError:
        return {"lsn": source.cursor}  # a position saved before positions were JSON
    return value if isinstance(value, dict) else {"value": value}


def _kind_settings(source: StreamSource) -> dict[str, Any]:
    kind = KINDS.get(source.kind)
    raw = dict((source.config_json or {}).get("settings") or {})
    return decrypt_sensitive_fields(raw, kind.secret_fields) if kind is not None else raw


def settings_for(db: Session, source: StreamSource) -> dict[str, Any]:
    """Everything a kind needs to read: its settings (secrets decrypted), the
    connection's when it reads through one, the tables and the slot."""
    kind = get_kind(source.kind)
    config = dict(source.config_json or {})
    settings: dict[str, Any] = {**_kind_settings(source), "source_id": source.id,
                                "tables": list(config.get("tables") or [])}
    if config.get("slot_name"):
        settings["slot_name"] = config["slot_name"]
    if kind.connection_types:
        connection = db.get(ExtractionConnection, source.connection_id) if source.connection_id else None
        if connection is None:
            raise LiveError("The connection this feed reads through has been deleted.")
        settings["connection"] = decrypt_sensitive_fields(
            dict(connection.config_json or {}), connection_secret_fields(connection.connector_type))
    return settings


def _shown_settings(source: StreamSource) -> dict[str, Any]:
    """Settings as the form shows them: secrets never leave, only whether one is set."""
    kind = KINDS.get(source.kind)
    raw = dict((source.config_json or {}).get("settings") or {})
    secret = set(kind.secret_fields) if kind is not None else set()
    return {key: (bool(value) if key in secret else value) for key, value in raw.items()}


def _read(source: StreamSource, *, connection_name: str | None, dataset_name: str | None,
          tables: list[LiveTable], recipe_count: int, outputs: list[uuid.UUID]) -> StreamSourceRead:
    kind = KINDS.get(source.kind)
    described = kind.describe() if kind is not None else {}
    config = source.config_json or {}
    return StreamSourceRead(
        id=source.id,
        project_id=source.project_id,
        name=source.name,
        kind=source.kind,
        kind_label=described.get("label", source.kind),
        family=described.get("family", "queue"),
        guarantee=described.get("guarantee", "at_least_once"),
        guarantee_title=described.get("guarantee_title", ""),
        guarantee_detail=described.get("guarantee_detail", ""),
        tier=described.get("tier", 4),
        tier_label=described.get("tier_label", ""),
        status=source.status,
        connection_id=source.connection_id,
        connection_name=connection_name,
        tables=list(config.get("tables") or []),
        slot_name=config.get("slot_name"),
        settings=_shown_settings(source),
        webhook_path=HOOK_PATH.replace("{token}", "…") if source.kind == "webhook" else None,
        cursor=source.cursor,
        dataset_id=source.dataset_id,
        dataset_name=dataset_name,
        events_count=source.events_count,
        behind=source.behind,
        read_every_seconds=source.read_every_seconds,
        save_every_seconds=source.save_every_seconds,
        keep_events_hours=source.keep_events_hours,
        failures=source.failures,
        next_read_at=source.next_read_at,
        last_read_count=source.last_read_count,
        last_event_at=source.last_event_at,
        last_polled_at=source.last_polled_at,
        last_materialised_at=source.last_materialised_at,
        last_error=source.last_error,
        live_tables=[_table_read(t) for t in tables],
        live_recipe_count=recipe_count,
        dataset_ids=list(dict.fromkeys(
            [d for d in [source.dataset_id, *[t.dataset_id for t in tables], *outputs] if d is not None])),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _table_read(table: LiveTable) -> LiveTableRead:
    return LiveTableRead(
        id=table.id, table_name=table.table_name, key_columns=list(table.key_columns_json or []),
        dataset_id=table.dataset_id, state=table.state, snapshot_rows=table.snapshot_rows,
        rows_now=table.rows_now, applied_seq=table.applied_seq, last_saved_at=table.last_saved_at,
        last_error=table.last_error,
    )


def _reads(db: Session, sources: list[StreamSource]) -> list[StreamSourceRead]:
    from service_datasets.models import Dataset

    none = [uuid.uuid4()]
    connections = {
        row.id: row.name for row in db.scalars(select(ExtractionConnection).where(
            ExtractionConnection.id.in_([s.connection_id for s in sources if s.connection_id] or none))).all()
    }
    datasets = {
        row.id: row.name for row in db.scalars(select(Dataset).where(
            Dataset.id.in_([s.dataset_id for s in sources if s.dataset_id] or none))).all()
    }
    ids = [s.id for s in sources] or none
    tables: dict[uuid.UUID, list[LiveTable]] = {}
    for table in db.scalars(select(LiveTable).where(LiveTable.source_id.in_(ids)).order_by(LiveTable.table_name)).all():
        tables.setdefault(table.source_id, []).append(table)
    recipes: dict[uuid.UUID, list[uuid.UUID | None]] = {}
    for source_id, output in db.execute(select(LiveRecipe.source_id, LiveRecipe.output_dataset_id).where(
            LiveRecipe.source_id.in_(ids))).all():
        recipes.setdefault(source_id, []).append(output)
    return [
        _read(s, connection_name=connections.get(s.connection_id) if s.connection_id else None,
              dataset_name=datasets.get(s.dataset_id) if s.dataset_id else None,
              tables=tables.get(s.id, []), recipe_count=len(recipes.get(s.id, [])),
              outputs=[o for o in recipes.get(s.id, []) if o is not None])
        for s in sources
    ]


def _get_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> StreamSource:
    source = db.scalar(select(StreamSource).where(StreamSource.id == source_id, StreamSource.project_id == project_id))
    if source is None:
        raise NotFoundError("Live feed not found.")
    return source


# ------------------------------------------------------------------ kinds


def list_kinds() -> list[dict[str, Any]]:
    return [kind.describe() for kind in KINDS.values()]


# ------------------------------------------------------------------ CRUD


def list_sources(db: Session, project_id: uuid.UUID, current_user: UserRead) -> StreamSourceListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    sources = list(db.scalars(select(StreamSource).where(StreamSource.project_id == project_id)
                              .order_by(StreamSource.created_at.desc())).all())
    return StreamSourceListResponse(items=_reads(db, sources))


def get_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> StreamSourceRead:
    ensure_owned_project(db, project_id, current_user.id)
    return _reads(db, [_get_source(db, project_id, source_id)])[0]


def _connection_for(db: Session, project_id: uuid.UUID, kind, connection_id: uuid.UUID | None) -> ExtractionConnection:
    if connection_id is None:
        raise BadRequestError(f"{kind.label} reads through a connection; choose one.")
    connection = db.scalar(select(ExtractionConnection).where(
        ExtractionConnection.id == connection_id, ExtractionConnection.project_id == project_id))
    if connection is None:
        raise NotFoundError("Connection not found in this project.")
    if connection.connector_type not in kind.connection_types:
        names = " or ".join(kind.connection_types)
        raise BadRequestError(
            f"{kind.label} follows a {names} connection; {connection.name!r} is {connection.connector_type}."
        )
    return connection


def _clean_tables(tables: list[str]) -> list[str]:
    out: list[str] = []
    for table in tables:
        cleaned = table.strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _validated_settings(kind, raw: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """The kind's settings, checked, with a secret left blank keeping the saved one."""
    merged = dict(raw or {})
    if existing:
        for key in kind.secret_fields:
            if not merged.get(key) and existing.get(key):
                merged[key] = existing[key]
    try:
        return kind.validate(merged)
    except LiveError as exc:
        raise BadRequestError(str(exc)) from exc


def create_source(db: Session, project_id: uuid.UUID, payload: StreamSourceCreate, current_user: UserRead) -> StreamSourceCreated:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.kind not in KINDS:
        raise BadRequestError(f"There is no live feed of kind {payload.kind!r}.")
    kind = KINDS[payload.kind]
    available, reason = kind.available()
    if not available:
        raise BadRequestError(reason or f"{kind.label} is not available here.")
    source_id = uuid.uuid4()
    token: str | None = None
    config: dict[str, Any] = {}
    connection_id: uuid.UUID | None = None
    tables = _clean_tables(payload.tables)
    if kind.family == "webhook":
        token = secrets.token_urlsafe(32)
    else:
        if kind.connection_types:
            connection_id = _connection_for(db, project_id, kind, payload.connection_id).id
        settings = _validated_settings(kind, payload.settings)
        config["settings"] = encrypt_sensitive_fields(settings, kind.secret_fields)
        if isinstance(kind, ChangeCaptureKind):
            if not tables:
                raise BadRequestError("Name at least one table to follow (schema.table or table).")
            config["tables"] = tables
        if kind.key == "postgres_cdc":
            config["slot_name"] = slot_name_for(payload.slot_name or payload.name, source_id)
    source = StreamSource(
        id=source_id,
        project_id=project_id,
        name=payload.name.strip(),
        kind=payload.kind,
        connection_id=connection_id,
        config_json=config,
        token_hash=_hash_token(token) if token else None,
        created_by_user_id=current_user.id,
        read_every_seconds=payload.read_every_seconds,
        save_every_seconds=payload.save_every_seconds,
        next_read_at=_now(),
    )
    db.add(source)
    # The feed's row first: nothing relates the two models, so the flush does
    # not order them, and PostgreSQL refuses a table row whose feed is not there yet.
    db.flush()
    for table in config.get("tables") or []:
        db.add(LiveTable(source_id=source_id, table_name=table))
    db.commit()
    db.refresh(source)
    read = _reads(db, [source])[0]
    return StreamSourceCreated(
        **read.model_dump(),
        token=token,
        webhook_path_with_token=HOOK_PATH.replace("{token}", token) if token else None,
    )


def update_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, payload: StreamSourceUpdate,
                  current_user: UserRead) -> StreamSourceRead:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    kind = get_kind(source.kind)
    config = dict(source.config_json or {})
    if payload.name is not None:
        source.name = payload.name.strip()
    if payload.status is not None:
        source.status = payload.status
        if payload.status == "active":
            source.failures = 0
            source.next_read_at = _now()
    for field in ("read_every_seconds", "save_every_seconds", "keep_events_hours"):
        value = getattr(payload, field)
        if value is not None:
            setattr(source, field, value)
    if payload.settings is not None and kind.family != "webhook":
        existing = _kind_settings(source)
        settings = _validated_settings(kind, payload.settings, existing=existing)
        config["settings"] = encrypt_sensitive_fields(settings, kind.secret_fields)
    if payload.tables is not None:
        if not isinstance(kind, ChangeCaptureKind):
            raise BadRequestError("Only a change-capture source follows tables.")
        tables = _clean_tables(payload.tables)
        if not tables:
            raise BadRequestError("A change-capture source follows at least one table.")
        known = {t.table_name: t for t in db.scalars(select(LiveTable).where(LiveTable.source_id == source.id)).all()}
        for name in tables:
            if name not in known:
                db.add(LiveTable(source_id=source.id, table_name=name))
        for name, table in known.items():
            if name not in tables:
                db.delete(table)  # its dataset stays, as it was when it stopped being followed
        config["tables"] = tables
    source.config_json = config
    db.commit()
    db.refresh(source)
    return _reads(db, [source])[0]


def delete_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    kind = KINDS.get(source.kind)
    if kind is not None and kind.family == "change_capture":
        # Release the slot, or the database keeps its change log for a reader that is gone.
        try:
            kind.forget(settings_for(db, source))
        except Exception:  # noqa: BLE001 - deleting the source must not depend on the source
            logger.warning("live_source_not_forgotten source_id=%s", source.id)
    # Explicit, not left to the database's cascade: these are this source's and
    # go with it whether or not the engine enforces the foreign keys.
    from service_extraction.models import LiveRecipeResult

    recipe_ids = list(db.scalars(select(LiveRecipe.id).where(LiveRecipe.source_id == source.id)).all())
    if recipe_ids:
        db.execute(sa_delete(LiveRecipeResult).where(LiveRecipeResult.live_recipe_id.in_(recipe_ids)))
        db.execute(sa_delete(LiveRecipe).where(LiveRecipe.id.in_(recipe_ids)))
    db.execute(sa_delete(LiveTable).where(LiveTable.source_id == source.id))
    db.execute(sa_delete(StreamEvent).where(StreamEvent.source_id == source.id))
    db.delete(source)
    db.commit()


def _outcome(outcome) -> LiveTestResult:
    return LiveTestResult(ok=outcome.ok, message=outcome.message, details=list(outcome.details))


def test_new_settings(db: Session, project_id: uuid.UUID, payload: StreamTestRequest, current_user: UserRead) -> LiveTestResult:
    """Whether settings would work, before they are saved."""
    ensure_owned_project(db, project_id, current_user.id)
    if payload.kind not in KINDS:
        raise BadRequestError(f"There is no live feed of kind {payload.kind!r}.")
    kind = KINDS[payload.kind]
    available, reason = kind.available()
    if not available:
        return LiveTestResult(ok=False, message=reason or "Not available here.", details=[])
    existing: dict[str, Any] | None = None
    if payload.source_id is not None:
        existing = _kind_settings(_get_source(db, project_id, payload.source_id))
    settings: dict[str, Any] = {**_validated_settings(kind, payload.settings, existing=existing),
                                "tables": _clean_tables(payload.tables), "source_id": payload.source_id}
    if kind.connection_types:
        connection = _connection_for(db, project_id, kind, payload.connection_id)
        settings["connection"] = decrypt_sensitive_fields(
            dict(connection.config_json or {}), connection_secret_fields(connection.connector_type))
    try:
        kind.guard(settings)
        return _outcome(kind.test(settings))
    except LiveError as exc:
        return LiveTestResult(ok=False, message=str(exc), details=[])


def test_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> LiveTestResult:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    try:
        kind, live = get_kind(source.kind), settings_for(db, source)
        kind.guard(live)
        return _outcome(kind.test(live))
    except LiveError as exc:
        return LiveTestResult(ok=False, message=str(exc), details=[])


def start_again(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> StreamSourceRead:
    """Forget the saved position and, for change capture, take every table's
    snapshot again. Kept data stays; the next versions start from now."""
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    kind = get_kind(source.kind)
    if kind.family == "webhook":
        raise BadRequestError("A webhook has no position to start again from.")
    if kind.family == "change_capture":
        try:
            kind.forget(settings_for(db, source))
        except Exception:  # noqa: BLE001 - starting again must work when the old position is broken
            logger.warning("live_source_not_forgotten source_id=%s", source.id)
        for table in db.scalars(select(LiveTable).where(LiveTable.source_id == source.id)).all():
            table.state = "waiting"
            table.last_error = None
    source.cursor = None
    source.status = "active"
    source.failures = 0
    source.last_error = None
    source.next_read_at = _now()
    db.commit()
    db.refresh(source)
    return _reads(db, [source])[0]


# ------------------------------------------------------------- events


def list_events(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead, *,
                limit: int = 50) -> StreamEventListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    rows = db.scalars(select(StreamEvent).where(StreamEvent.source_id == source.id)
                      .order_by(StreamEvent.seq.desc()).limit(limit)).all()
    return StreamEventListResponse(items=[StreamEventRead.model_validate(r, from_attributes=True) for r in rows])


def store_messages(db: Session, source: StreamSource, messages: list[Message], *, now: datetime | None = None) -> int:
    """Add what arrived as events with the next sequence numbers; an event whose
    position is already stored (or repeated within the batch) is skipped.
    Flushes, does not commit: the caller commits with the position."""
    if not messages:
        return 0
    wanted = [m.position for m in messages if m.position]
    seen: set[str] = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        seen.update(db.scalars(select(StreamEvent.position).where(
            StreamEvent.source_id == source.id, StreamEvent.position.in_(chunk))).all())
    fresh: list[Message] = []
    for message in messages:
        if message.position:
            if message.position in seen:
                continue
            seen.add(message.position)
        fresh.append(message)
    if not fresh:
        return 0
    # Take the numbers under the source's row lock (FOR UPDATE on PostgreSQL;
    # SQLite has one writer), so two posts at once never get the same one.
    base = int(db.scalar(select(StreamSource.events_count).where(StreamSource.id == source.id).with_for_update()) or 0)
    moment = now or _now()
    db.execute(
        StreamEvent.__table__.insert(),
        [
            {"id": uuid.uuid4(), "source_id": source.id, "seq": base + index + 1, "kind": message.kind[:16],
             "table_name": message.table, "position": message.position, "payload_json": message.payload,
             "received_at": moment}
            for index, message in enumerate(fresh)
        ],
    )
    db.execute(update(StreamSource).where(StreamSource.id == source.id)
               .values(events_count=base + len(fresh), last_event_at=moment)
               .execution_options(synchronize_session=False))
    source.events_count = base + len(fresh)
    source.last_event_at = moment
    return len(fresh)


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
    if source.status == "paused":
        raise ConflictError("This webhook is paused.")
    text_body = body.decode("utf-8", errors="replace")
    if content_type and "json" in content_type:
        try:
            decoded = json.loads(text_body or "null")
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"The body is not valid JSON: {exc.msg}.") from exc
        payload: dict[str, Any] = decoded if isinstance(decoded, dict) else {"value": decoded}
    else:
        payload = {"body": text_body}
    kept = {k: v for k, v in headers.items() if k.lower() in KEPT_HEADERS}
    if kept:
        payload = {**payload, "_headers": kept}
    position = idempotency_position(headers)
    for attempt in range(3):
        try:
            stored = store_messages(db, source, [Message("webhook", payload, position)])
            seq = source.events_count
            db.commit()
            break
        except IntegrityError:
            db.rollback()  # another post took the same number first; take the next one
            db.refresh(source)
            if attempt == 2:
                raise
    if stored:
        event = db.scalar(select(StreamEvent).where(StreamEvent.source_id == source.id, StreamEvent.seq == seq))
    else:  # sent before with the same Idempotency-Key: the event it already made
        event = db.scalar(select(StreamEvent).where(StreamEvent.source_id == source.id, StreamEvent.position == position))
    return StreamEventRead.model_validate(event, from_attributes=True)


# ---------------------------------------------------------------- reading


def _claim(db: Session, source: StreamSource, owner: str) -> bool:
    now = _now()
    claimed = db.execute(
        update(StreamSource)
        .where(StreamSource.id == source.id,
               (StreamSource.claim_expires_at.is_(None)) | (StreamSource.claim_expires_at < now)
               | (StreamSource.claim_owner_id == owner))
        .values(claim_owner_id=owner, claim_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    db.refresh(source)
    return bool(claimed)


def _release(db: Session, source_id: uuid.UUID, owner: str) -> None:
    db.execute(update(StreamSource).where(StreamSource.id == source_id, StreamSource.claim_owner_id == owner)
               .values(claim_owner_id=None, claim_expires_at=None).execution_options(synchronize_session=False))
    db.commit()


def read_source(db: Session, source: StreamSource, *, budget_seconds: float = PASS_SECONDS,
                storage_backend=None, settings=None) -> dict[str, Any]:
    """Take what is waiting at the source, until it has no more or the budget
    runs out. Change capture takes its position and snapshots first."""
    kind = get_kind(source.kind)
    totals = {"read": 0, "stored": 0, "rounds": 0, "notes": []}
    if kind.family == "webhook":
        return totals
    live = settings_for(db, source)
    kind.guard(live)
    if isinstance(kind, ChangeCaptureKind):
        if source.cursor is None:
            position = kind.start_position(live)
            source.cursor = json.dumps(position)
            if position.get("created"):
                totals["notes"].append("Made the replication slot this feed reads from.")
            db.commit()
        waiting = list(db.scalars(select(LiveTable).where(LiveTable.source_id == source.id, LiveTable.state == "waiting")).all())
        for table in waiting:
            _snapshot(db, source, kind, live, table, storage_backend=storage_backend, settings=settings)
    started = time.monotonic()
    while True:
        batch = kind.read(live, cursor_of(source), limit=READ_BATCH)
        try:
            stored = store_messages(db, source, batch.messages)
            if batch.cursor is not None:
                source.cursor = json.dumps(batch.cursor)
            source.behind = batch.behind
            source.last_polled_at = _now()
            db.commit()
        except Exception:
            db.rollback()
            batch.finish(False)
            raise
        try:
            batch.finish(True)
        except Exception:  # noqa: BLE001 - saved already; the source sends it again and it is skipped
            logger.warning("live_source_acknowledge_failed source_id=%s", source.id, exc_info=True)
        totals["read"] += len(batch.messages)
        totals["stored"] += stored
        totals["rounds"] += 1
        totals["notes"].extend(batch.notes)
        if not batch.more or time.monotonic() - started > budget_seconds:
            break
    return totals


def poll_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead | None,
                *, storage_backend=None, settings=None) -> StreamPollResponse:
    """Read now, outside the runner's schedule ("Read now")."""
    if current_user is not None:
        ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    kind = get_kind(source.kind)
    if kind.family == "webhook":
        raise BadRequestError("A webhook is not read; events arrive at its address.")
    owner = f"request-{uuid.uuid4()}"
    if not _claim(db, source, owner):
        raise ConflictError("This feed is being read right now; try again in a moment.")
    try:
        totals = read_source(db, source, storage_backend=storage_backend, settings=settings)
        _succeeded(db, source, totals["stored"])
    except Exception as exc:  # noqa: BLE001 - recorded on the source, said in its words
        db.rollback()
        message = _failed(db, source, exc)
        raise BadRequestError(message) from exc
    finally:
        _release(db, source.id, owner)
    db.refresh(source)
    return StreamPollResponse(
        source=_reads(db, [source])[0], read=totals["read"], stored=totals["stored"], rounds=totals["rounds"],
        notes=totals["notes"], guarantee=get_kind(source.kind).describe()["guarantee_title"],
    )


def _succeeded(db: Session, source: StreamSource, stored: int) -> None:
    source.failures = 0
    source.last_error = None
    source.failure_notified_at = None
    if source.status == "failing":
        source.status = "active"
    source.last_read_count = stored
    source.next_read_at = _now() + timedelta(seconds=max(1, int(source.read_every_seconds or 5)))
    db.commit()


def _failed(db: Session, source: StreamSource, exc: Exception) -> str:
    message = str(exc) if isinstance(exc, LiveError) else (
        str(getattr(exc, "detail", "")) or f"{exc.__class__.__name__}: {str(exc)[:300]}")
    db.refresh(source)
    source.failures = int(source.failures or 0) + 1
    source.last_error = message[:1000]
    source.last_polled_at = _now()
    if source.status == "active":
        source.status = "failing"
    wait = min(BACKOFF_LIMIT_SECONDS, max(int(source.read_every_seconds or 5), 2 ** min(source.failures, 9)))
    source.next_read_at = _now() + timedelta(seconds=wait)
    if source.failures >= NOTIFY_AFTER and source.failure_notified_at is None:
        source.failure_notified_at = _now()
        _tell_owner(db, source, message)
    db.commit()
    return message


def _tell_owner(db: Session, source: StreamSource, message: str) -> None:
    try:
        from service_notifications.external_dispatch import dispatch_external_notifications
        from service_notifications.service import create_user_notification

        title = f"{source.name} keeps failing"
        body = f"{count_of(source.failures, 'try', 'tries')} in a row failed. The last said: {message[:300]}"
        if source.created_by_user_id:
            create_user_notification(db, user_id=source.created_by_user_id, project_id=source.project_id,
                                     type="live_source_failed", level="error", title=title, message=body,
                                     related_dataset_id=source.dataset_id)
        dispatch_external_notifications(db, project_id=source.project_id, event_type="live_source_failed",
                                        title=title, message=body, level="error")
    except Exception:  # noqa: BLE001 - telling must not stop recording
        logger.warning("live_source_notify_failed source_id=%s", source.id, exc_info=True)


# ------------------------------------------------------------- snapshot


def _flatten(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rows as columns: nested values (a document's fields) become dotted columns."""
    if not rows:
        return pd.DataFrame()
    if any(isinstance(v, dict) for row in rows[:50] for v in row.values()):
        frame = pd.json_normalize(rows, sep=".")
    else:
        frame = pd.DataFrame.from_records(rows)
    for column in frame.columns:
        if frame[column].map(lambda v: isinstance(v, (list, dict))).any():
            frame[column] = frame[column].map(lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v)
    return frame


def _actor(db: Session, source: StreamSource) -> UserRead:
    """Whom a saved version is by: the source's maker, or the project's owner
    once the maker has gone."""
    from service_auth.models import User
    from service_projects.models import Project

    for user_id in (source.created_by_user_id, getattr(db.get(Project, source.project_id), "owner_user_id", None)):
        user = db.get(User, user_id) if user_id else None
        if user is not None and user.is_active:
            return UserRead.model_validate(user)
    raise LiveError("Nobody who can save this feed's data is left: its maker and the project's owner are inactive.")


def _snapshot(db: Session, source: StreamSource, kind: ChangeCaptureKind, live: dict[str, Any], table: LiveTable,
              *, storage_backend, settings) -> None:
    """Read one table whole and make it the first version of its dataset."""
    table.state = "snapshot"
    table.last_error = None
    applied = int(source.events_count or 0)
    db.commit()
    try:
        keys = kind.key_columns(live, table.table_name)
        rows: list[dict[str, Any]] = []
        for chunk in kind.snapshot(live, table.table_name, chunk=SNAPSHOT_CHUNK):
            rows.extend(chunk)
        frame = _flatten(rows)
        if not keys:
            table.key_columns_json = []
            table.state = "log_only"
            table.snapshot_rows = len(frame)
            db.commit()
            return
        if storage_backend is None or settings is None:
            raise LiveError("Saving needs storage; the runner takes each table's first copy.")
        dataset = publish_frame(db, source, dataset_id=table.dataset_id, name=f"{table.table_name} (live)",
                                frame=frame, storage_backend=storage_backend, settings=settings,
                                source_name=f"{source.name}: {table.table_name}")
        table.dataset_id = dataset.id
        table.key_columns_json = keys
        table.state = "following"
        table.snapshot_rows = int(len(frame))
        table.rows_now = int(len(frame))
        table.applied_seq = applied
        table.last_saved_at = _now()
        db.commit()
    except Exception as exc:
        db.rollback()
        table = db.get(LiveTable, table.id)
        if table is not None:
            table.state = "waiting"
            table.last_error = str(exc)[:1000]
            db.commit()
        raise


# ----------------------------------------------------------------- saving


def _csv(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def typed(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame as the dataset will read it back: through CSV, so a batch and
    the saved data have the same column types."""
    if frame.empty:
        return frame
    return pd.read_csv(io.BytesIO(_csv(frame)))


def publish_frame(db: Session, source: StreamSource, *, dataset_id: uuid.UUID | None, name: str,
                  frame: pd.DataFrame | None = None, csv_bytes: bytes | None = None,
                  storage_backend, settings, source_name: str, check_frame: pd.DataFrame | None = None):
    """Write a new version of a live source's dataset (making the dataset the
    first time), after its contract has judged the new data (C1)."""
    from service_quality.data_contracts import check_new_data

    actor = _actor(db, source)
    data = csv_bytes if csv_bytes is not None else _csv(frame if frame is not None else pd.DataFrame())
    if len(data) > settings.max_upload_size_bytes:
        raise LiveError(f"{name} would be larger than the largest dataset allowed here; keep fewer events or tables.")
    judged = check_frame if check_frame is not None else (
        frame if frame is not None else pd.read_csv(io.BytesIO(data)) if data.strip() else pd.DataFrame())
    dataset = get_dataset_model_for_project(db, source.project_id, dataset_id) if dataset_id else None
    verdict = None
    if dataset is not None:
        verdict = check_new_data(db, dataset=dataset, frame=judged, source_type="stream", source_id=source.id,
                                 source_name=source_name, actor_user_id=actor.id)
    else:
        dataset = create_uploaded_dataset_placeholder(
            db, project_id=source.project_id, name=name[:160], original_filename=f"{name[:80] or 'live'}.csv",
            file_type="csv", file_size_bytes=len(data), current_user=actor, pipeline_run_id=None,
        )
    relative_path, _ = build_derived_dataset_path(project_id=str(source.project_id), dataset_id=str(dataset.id),
                                                  basename="live.csv")
    stored = storage_backend.save_upload(relative_path=relative_path, file_bytes=data)
    schema = infer_schema(dataframe=judged)
    dataset.file_type = "csv"
    dataset.file_size_bytes = len(data)
    finalize_dataset_materialization_success(
        db, dataset=dataset, file_path=stored.relative_path, file_name=stored.file_name,
        schema_json=schema, schema_snapshot={"columns": schema["columns"]},
        preview_json=build_preview(dataframe=judged, limit=settings.preview_row_limit),
        profile_json=build_profile(dataframe=judged, sample_limit=settings.profile_sample_value_limit,
                                   file_size_bytes=len(data)),
        row_count=int(len(judged)), column_count=int(len(judged.columns)),
        content_hash=content_digest(data), created_by_user_id=actor.id, contract_verdict=verdict,
    )
    return dataset


def events_frame(source: StreamSource, events: list[StreamEvent]) -> pd.DataFrame:
    """Events as rows: the arrival details, then the event's own fields.

    A change is its row (or, for a delete, its old key); a queue message its
    value's fields with `message_` details; a post its body's fields.
    """
    rows: list[dict[str, Any]] = []
    for event in events:
        base: dict[str, Any] = {"seq": event.seq, "kind": event.kind,
                                "received_at": _aware(event.received_at).isoformat() if event.received_at else None}
        payload = event.payload_json or {}
        if event.kind in ("insert", "update", "delete"):
            base["table"] = event.table_name
            for name in ("lsn", "xid"):
                if payload.get(name) is not None:
                    base[name] = payload[name]
            values = payload.get("row") or payload.get("old_key") or {}
            base.update(_flatten([values]).iloc[0].to_dict() if values else {})
        elif event.kind == "message":
            value = payload.get("value")
            if isinstance(value, dict):
                flat = pd.json_normalize(value, sep=".").to_dict(orient="records")
                base.update(flat[0] if flat else {})
            else:
                base["value"] = value
            for name, item in payload.items():
                if name not in ("value", "format"):
                    base[f"message_{name}"] = item
        else:
            flat = pd.json_normalize({k: v for k, v in payload.items() if k != "_headers"}, sep=".").to_dict(orient="records")
            base.update(flat[0] if flat else {})
        rows.append({k: (json.dumps(v, default=str) if isinstance(v, (list, dict)) else v) for k, v in base.items()})
    return pd.DataFrame(rows)


def _previous_text(storage_backend, dataset) -> pd.DataFrame | None:
    """The dataset's current version as text, exactly as stored, to add rows to."""
    if dataset is None or not dataset.file_path:
        return None
    try:
        payload = storage_backend.read_bytes(dataset.file_path)
    except (FileNotFoundError, OSError):
        return None
    if not payload.strip():
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(payload), dtype=str, keep_default_na=False)


def _append_csv(previous: pd.DataFrame | None, new_rows: pd.DataFrame) -> bytes:
    """The old rows exactly as they were stored, then the new ones; a column only
    one side has is empty on the other."""
    fresh = new_rows.astype(object).where(new_rows.notna(), "")
    fresh = fresh.map(lambda v: v if isinstance(v, str) else str(v))
    if previous is None or previous.empty and not len(previous.columns):
        return _csv(fresh)
    columns = list(previous.columns) + [c for c in fresh.columns if c not in previous.columns]
    combined = pd.concat([previous.reindex(columns=columns, fill_value=""),
                          fresh.reindex(columns=columns, fill_value="")], ignore_index=True)
    return _csv(combined)


def _save_log(db: Session, source: StreamSource, upto: int, *, storage_backend, settings) -> int:
    events = list(db.scalars(select(StreamEvent).where(
        StreamEvent.source_id == source.id, StreamEvent.seq > source.log_saved_seq, StreamEvent.seq <= upto)
        .order_by(StreamEvent.seq)).all())
    if not events:
        return 0
    dataset = get_dataset_model_for_project(db, source.project_id, source.dataset_id) if source.dataset_id else None
    previous = _previous_text(storage_backend, dataset)
    data = _append_csv(previous, events_frame(source, events))
    dataset = publish_frame(db, source, dataset_id=source.dataset_id, name=f"{source.name} (every event)",
                            csv_bytes=data, storage_backend=storage_backend, settings=settings, source_name=source.name)
    source.dataset_id = dataset.id
    source.log_saved_seq = upto
    db.commit()
    return len(events)


def _key_text(value: Any) -> str:
    """A key value as text both a snapshot's row and a change's agree on."""
    if value is None or (isinstance(value, float) and value != value):
        return "\x00"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def apply_changes(current: pd.DataFrame, changes: list[StreamEvent], keys: list[str]) -> pd.DataFrame:
    """The table after its changes, in order: an insert or update replaces the
    row with its key (a column the change does not carry keeps its value),
    a delete removes it. Rows come back in key order."""
    rows: dict[tuple[str, ...], dict[str, Any] | None] = {}
    current_index: dict[tuple[str, ...], int] = {}
    if not current.empty:
        key_frame = current[keys].map(_key_text) if all(k in current.columns for k in keys) else None
        if key_frame is not None:
            current_index = {tuple(row): index for index, row in enumerate(key_frame.itertuples(index=False, name=None))}
    for change in changes:
        payload = change.payload_json or {}
        values = payload.get("row") or {}
        flat = _flatten([values]).iloc[0].to_dict() if values else {}
        old = payload.get("old_key") or {}
        old_flat = _flatten([old]).iloc[0].to_dict() if old else {}
        # The row's key: a delete names it in its old key (PostgreSQL puts it in
        # the row), anything else in its new values.
        source_of_key = {**flat, **old_flat} if change.kind == "delete" else {**old_flat, **flat}
        if any(k not in source_of_key for k in keys):
            continue  # nothing to find the row by
        key = tuple(_key_text(source_of_key[k]) for k in keys)
        if change.kind == "delete":
            rows[key] = None
            continue
        before = rows.get(key)
        if before is None and key not in rows and key in current_index:
            before = current.iloc[current_index[key]].to_dict()
        if change.kind == "update" and before:
            rows[key] = {**before, **flat}
        else:
            rows[key] = dict(flat)
        if old_flat and change.kind == "update":
            if all(k in old_flat for k in keys):
                old_key = tuple(_key_text(old_flat[k]) for k in keys)
                if old_key != key:
                    rows[old_key] = None  # the key itself changed: the old row is gone
    keep = current
    if not current.empty and current_index:
        changed = [index for key, index in current_index.items() if key in rows]
        keep = current.drop(index=current.index[changed]) if changed else current
    added = pd.DataFrame([row for row in rows.values() if row is not None])
    if added.empty:
        result = keep
    elif keep.empty and not len(keep.columns):
        result = added
    else:
        # Stacked as plain values: the types are worked out again when the
        # version is read back, and pandas no longer guesses them from empty columns.
        columns = list(keep.columns) + [c for c in added.columns if c not in keep.columns]
        stacked = np.vstack([keep.reindex(columns=columns).to_numpy(dtype=object),
                             added.reindex(columns=columns).to_numpy(dtype=object)])
        result = pd.DataFrame(stacked, columns=columns)
    if result.empty or not all(k in result.columns for k in keys):
        return result.reset_index(drop=True)
    order = result[keys].map(_key_text)
    numeric = all(pd.to_numeric(result[k], errors="coerce").notna().all() for k in keys)
    sort_frame = result[keys].apply(pd.to_numeric) if numeric else order
    return result.loc[sort_frame.sort_values(by=keys, kind="stable").index].reset_index(drop=True)


def _save_table(db: Session, source: StreamSource, table: LiveTable, upto: int, *, storage_backend, settings) -> int:
    if table.state != "following" or table.dataset_id is None:
        return 0
    changes = list(db.scalars(select(StreamEvent).where(
        StreamEvent.source_id == source.id, StreamEvent.seq > table.applied_seq, StreamEvent.seq <= upto,
        StreamEvent.kind.in_(("insert", "update", "delete"))).order_by(StreamEvent.seq)).all())
    changes = [c for c in changes if _same_table(c.table_name, table.table_name)]
    if not changes:
        table.applied_seq = upto
        db.commit()
        return 0
    dataset = get_dataset_model_for_project(db, source.project_id, table.dataset_id)
    from service_ingestion.read_copy import frame_of

    payload = storage_backend.read_bytes(dataset.file_path)
    current = frame_of(storage_backend, dataset.file_path, payload, file_type=dataset.file_type or "csv",
                       spec=dataset.ingest_spec_json) if payload.strip() else pd.DataFrame()
    after = apply_changes(current, changes, list(table.key_columns_json or []))
    publish_frame(db, source, dataset_id=table.dataset_id, name=f"{table.table_name} (live)",
                  frame=typed(after), storage_backend=storage_backend, settings=settings,
                  source_name=f"{source.name}: {table.table_name}")
    table.applied_seq = upto
    table.rows_now = int(len(after))
    table.last_saved_at = _now()
    table.last_error = None
    db.commit()
    return len(changes)


def _plain_name(table: str) -> str:
    return "".join(ch for ch in table if ch not in '"`[]').lower()


def _same_table(event_table: str | None, followed: str) -> bool:
    """Whether a change is to a followed table. The change names it as the
    database does (`public.orders`); the source may name it without its schema."""
    if not event_table:
        return False
    a, b = _plain_name(event_table), _plain_name(followed)
    if a == b:
        return True
    if "." not in a or "." not in b:
        return a.split(".")[-1] == b.split(".")[-1]
    return False


def save_source_now(db: Session, source: StreamSource, *, storage_backend, settings) -> dict[str, int]:
    """Save the log, the tables and the live recipes' outputs, each in its own
    transaction, up to the events stored when the save began."""
    from service_extraction import live_recipes

    upto = int(source.events_count or 0)
    saved = {"log": 0, "tables": 0, "recipes": 0}
    saved["log"] = _save_log(db, source, upto, storage_backend=storage_backend, settings=settings)
    for table in db.scalars(select(LiveTable).where(LiveTable.source_id == source.id)).all():
        try:
            saved["tables"] += _save_table(db, source, table, upto, storage_backend=storage_backend, settings=settings)
        except Exception as exc:
            db.rollback()
            failed = db.get(LiveTable, table.id)
            if failed is not None:
                failed.last_error = str(getattr(exc, "detail", "") or exc)[:1000]
                db.commit()
            raise
    saved["recipes"] = live_recipes.save_outputs(db, source, storage_backend=storage_backend, settings=settings)
    source.last_materialised_at = _now()
    db.commit()
    return saved


def materialise_source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead,
                       storage_backend, settings) -> StreamMaterialiseResponse:
    """Save now ("Save now"): every dataset this source keeps, up to what has arrived."""
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    if not source.events_count and not db.scalar(select(func.count()).select_from(LiveTable).where(
            LiveTable.source_id == source.id, LiveTable.state == "following")):
        raise BadRequestError("Nothing has arrived yet, so there is nothing to save.")
    try:
        saved = save_source_now(db, source, storage_backend=storage_backend, settings=settings)
    except LiveError as exc:
        raise BadRequestError(str(exc)) from exc
    db.refresh(source)
    from service_datasets.models import DatasetVersion

    version = db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == source.dataset_id)) \
        if source.dataset_id else None
    return StreamMaterialiseResponse(
        source=_reads(db, [source])[0], dataset_id=source.dataset_id, version_number=int(version or 0),
        events_saved=saved["log"], changes_applied=saved["tables"], recipe_outputs=saved["recipes"],
    )


# ------------------------------------------------------------- the pass


def due_sources(db: Session, *, now: datetime | None = None, limit: int = 100) -> list[uuid.UUID]:
    moment = now or _now()
    return list(db.scalars(
        select(StreamSource.id)
        .where(StreamSource.status.in_(("active", "failing")),
               (StreamSource.next_read_at.is_(None)) | (StreamSource.next_read_at <= moment))
        .order_by(StreamSource.next_read_at.asc().nulls_first())
        .limit(limit)
    ).all())


def run_pass(db: Session, source_id: uuid.UUID, *, owner: str, storage_backend, settings) -> dict[str, Any]:
    """The runner's turn for one source: read, process its live recipes, save
    when due. A failure is recorded on the source and backs it off."""
    from service_extraction import live_recipes

    source = db.get(StreamSource, source_id)
    result: dict[str, Any] = {"source_id": str(source_id), "stored": 0, "saved": None, "error": None}
    if source is None or source.status == "paused":
        return result
    if not _claim(db, source, owner):
        return result
    try:
        totals = read_source(db, source, storage_backend=storage_backend, settings=settings)
        result["stored"] = totals["stored"]
        live_recipes.process_source(db, source, storage_backend=storage_backend, settings=settings)
        last = _aware(source.last_materialised_at)
        due = last is None or _now() - last >= timedelta(seconds=max(1, int(source.save_every_seconds or 60)))
        if due and _has_unsaved(db, source):
            result["saved"] = save_source_now(db, source, storage_backend=storage_backend, settings=settings)
        trim_events(db, source)
        _succeeded(db, source, totals["stored"])
    except Exception as exc:  # noqa: BLE001 - recorded on the source, backs it off
        db.rollback()
        result["error"] = _failed(db, source, exc)
        logger.warning("live_source_pass_failed source_id=%s error=%s", source_id, result["error"])
    finally:
        _release(db, source_id, owner)
    return result


def _has_unsaved(db: Session, source: StreamSource) -> bool:
    from service_extraction import live_recipes

    top = int(source.events_count or 0)
    if top > int(source.log_saved_seq or 0):
        return True
    if db.scalar(select(func.count()).select_from(LiveTable).where(
            LiveTable.source_id == source.id, LiveTable.state == "following", LiveTable.applied_seq < top)):
        return True
    return live_recipes.has_unsaved(db, source)


def trim_events(db: Session, source: StreamSource, *, now: datetime | None = None) -> int:
    """Forget events older than `keep_events_hours` that every output already has."""
    from service_extraction.models import LiveRecipe as Recipe

    marks = [int(source.log_saved_seq or 0)]
    marks += [int(s or 0) for s in db.scalars(select(LiveTable.applied_seq).where(
        LiveTable.source_id == source.id, LiveTable.state == "following")).all()]
    for recipe in db.scalars(select(Recipe).where(Recipe.source_id == source.id, Recipe.status == "active")).all():
        marks.append(int(recipe.processed_seq or 0))
        if not recipe.window_json:
            marks.append(int(recipe.saved_seq or 0))
    upto = min(marks)
    before = (now or _now()) - timedelta(hours=max(1, int(source.keep_events_hours or 168)))
    gone = db.execute(sa_delete(StreamEvent).where(
        StreamEvent.source_id == source.id, StreamEvent.seq <= upto, StreamEvent.received_at < before)).rowcount
    if gone:
        db.commit()
    return int(gone or 0)


def throughput(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead, *,
               minutes: int = 60) -> list[ThroughputPoint]:
    """Events stored per minute over the last hour, oldest first, gaps as zero."""
    ensure_owned_project(db, project_id, current_user.id)
    source = _get_source(db, project_id, source_id)
    now = _now().replace(second=0, microsecond=0)
    since = now - timedelta(minutes=minutes - 1)
    if db.get_bind().dialect.name == "postgresql":
        bucket = func.date_trunc("minute", StreamEvent.received_at)
    else:
        bucket = func.strftime("%Y-%m-%d %H:%M", StreamEvent.received_at)
    counts: dict[datetime, int] = {}
    for minute, count in db.execute(select(bucket, func.count()).where(
            StreamEvent.source_id == source.id, StreamEvent.received_at >= since).group_by(bucket)).all():
        moment = minute if isinstance(minute, datetime) else datetime.strptime(str(minute), "%Y-%m-%d %H:%M")
        counts[_aware(moment).astimezone(UTC).replace(second=0, microsecond=0)] = int(count)
    return [ThroughputPoint(minute=since + timedelta(minutes=i), events=counts.get(since + timedelta(minutes=i), 0))
            for i in range(minutes)]
