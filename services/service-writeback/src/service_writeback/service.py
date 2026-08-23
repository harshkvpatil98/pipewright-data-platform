"""Orchestration: staging, planning, committing, auditing.

The routes are thin; the decisions live here so they can be tested without HTTP.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger
from service_projects.contracts import ensure_owned_project

from service_writeback.compiler import CompiledChange, compile_change_set
from service_writeback.edits import _UNRECORDED, Edit, EditKind, validate_all
from service_writeback.execute import (
    BlastRadius,
    ChangeResult,
    commit as run_commit,
    count_rows,
    dry_run,
    export_as_migration,
)
from service_writeback.identity import TableShape, read_shape
from service_writeback.models import ChangeSet, ChangeSetEdit
from service_writeback.read import RowPage, read_rows
from service_writeback.schemas import EditInput

logger = get_logger(__name__)

#: A change set that has been applied is history, not a draft.
_TERMINAL = frozenset({"committed", "discarded"})

#: Injected by the gateway so this service never imports service-extraction --
#: the registered-resolver pattern used across the platform to avoid cycles.
_engine_resolver: Callable[[Session, uuid.UUID, uuid.UUID], Engine] | None = None


def register_engine_resolver(
    resolver: Callable[[Session, uuid.UUID, uuid.UUID], Engine],
) -> None:
    """Supply the function that turns (project, connection) into a live engine."""
    global _engine_resolver
    _engine_resolver = resolver


def _engine_for(db: Session, project_id: uuid.UUID, connection_id: uuid.UUID) -> Engine:
    if _engine_resolver is None:
        raise BadRequestError(
            "Write-back is not available: no database connection provider is registered."
        )
    return _engine_resolver(db, project_id, connection_id)


# --------------------------------------------------------------------- reading


def get_change_set(
    db: Session, project_id: uuid.UUID, change_set_id: uuid.UUID, user_id: uuid.UUID
) -> ChangeSet:
    ensure_owned_project(db, project_id, user_id)
    change_set = db.get(ChangeSet, change_set_id)
    if change_set is None or change_set.project_id != project_id:
        raise NotFoundError("That change set does not exist in this project.")
    return change_set


def list_change_sets(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 100
) -> list[ChangeSet]:
    ensure_owned_project(db, project_id, user_id)
    return list(
        db.scalars(
            select(ChangeSet)
            .where(ChangeSet.project_id == project_id)
            .order_by(ChangeSet.created_at.desc(), ChangeSet.id)
            .limit(limit)
        ).all()
    )


def describe_table(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    table: str,
    schema: str | None,
    designated: list[str] | None,
    user_id: uuid.UUID,
) -> TableShape:
    """Report whether this table can be edited at all, before anyone starts."""
    ensure_owned_project(db, project_id, user_id)
    engine = _engine_for(db, project_id, connection_id)
    return read_shape(engine, table=table, schema=schema, designated=designated)


def read_table_rows(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    table: str,
    schema: str | None,
    designated: list[str] | None,
    limit: int,
    offset: int,
    order_by: str | None,
    descending: bool,
    user_id: uuid.UUID,
) -> RowPage:
    """A page of live rows, ordered by the key the edits will use."""
    ensure_owned_project(db, project_id, user_id)
    engine = _engine_for(db, project_id, connection_id)
    shape = read_shape(engine, table=table, schema=schema, designated=designated)
    return read_rows(
        engine,
        shape,
        limit=limit,
        offset=offset,
        order_by=order_by,
        descending=descending,
    )


# --------------------------------------------------------------------- staging


def create_change_set(
    db: Session,
    project_id: uuid.UUID,
    *,
    connection_id: uuid.UUID,
    table_name: str,
    table_schema: str | None,
    name: str,
    designated_key: list[str] | None,
    user_id: uuid.UUID,
) -> ChangeSet:
    ensure_owned_project(db, project_id, user_id)
    # Resolving the shape now means an unusable table is refused when somebody
    # starts editing, not after they have staged twenty changes.
    engine = _engine_for(db, project_id, connection_id)
    shape = read_shape(engine, table=table_name, schema=table_schema, designated=designated_key)
    if not shape.identity.usable:
        raise BadRequestError(shape.identity.reason)

    change_set = ChangeSet(
        project_id=project_id,
        connection_id=connection_id,
        table_name=table_name,
        table_schema=table_schema,
        name=name,
        designated_key=list(designated_key) if designated_key else None,
        created_by_user_id=user_id,
        status="draft",
    )
    db.add(change_set)
    db.commit()
    db.refresh(change_set)
    return change_set


def add_edits(db: Session, change_set: ChangeSet, inputs: list[EditInput]) -> ChangeSet:
    _require_draft(change_set)
    if not inputs:
        raise BadRequestError("No edits were supplied.")
    shape = _shape_for(db, change_set)

    # Validated against the change set as a whole -- existing edits plus this
    # batch -- so "add a column, then type into it" works, and so a rejected
    # batch leaves the change set exactly as it was.
    existing = [
        _to_edit(EditInput(**{**row.payload_json, "kind": row.kind}))
        for row in sorted(change_set.edits, key=lambda row: (row.sequence, str(row.id)))
    ]
    incoming = [_to_edit(payload) for payload in inputs]
    validate_all(
        existing + incoming,
        columns=shape.columns,
        key_columns=shape.identity.columns,
    )

    next_sequence = 1 + max((row.sequence for row in change_set.edits), default=-1)
    for offset, payload in enumerate(inputs):
        db.add(
            ChangeSetEdit(
                change_set_id=change_set.id,
                sequence=next_sequence + offset,
                kind=payload.kind,
                payload_json=payload.model_dump(mode="json"),
            )
        )
    db.commit()
    db.refresh(change_set)
    return change_set


def remove_edit(db: Session, change_set: ChangeSet, edit_id: uuid.UUID) -> ChangeSet:
    _require_draft(change_set)
    edit = db.get(ChangeSetEdit, edit_id)
    if edit is None or edit.change_set_id != change_set.id:
        raise NotFoundError("That edit is not part of this change set.")
    db.delete(edit)
    db.commit()
    db.refresh(change_set)
    return change_set


def discard(db: Session, change_set: ChangeSet) -> ChangeSet:
    _require_draft(change_set)
    change_set.status = "discarded"
    db.commit()
    db.refresh(change_set)
    return change_set


# -------------------------------------------------------------------- applying


def plan(db: Session, change_set: ChangeSet) -> dict[str, Any]:
    """Rehearse the change and report what it would do. Nothing is written."""
    engine, shape, compiled = _compile_for(db, change_set)
    result = dry_run(engine, compiled)
    total = count_rows(engine, shape)
    return {
        "shape": shape,
        "compiled": compiled,
        "result": result,
        "table_rows": total,
        "blast_radius": BlastRadius(result.rows_affected, total),
    }


def commit_change_set(
    db: Session,
    change_set: ChangeSet,
    *,
    confirm_table_name: str | None,
    allow_conflicts: bool,
    user_id: uuid.UUID,
) -> ChangeResult:
    _require_draft(change_set)
    engine, shape, compiled = _compile_for(db, change_set)

    # Rehearse first, always. The confirmation gate needs a real number, and an
    # estimate is wrong exactly when it matters.
    rehearsal = dry_run(engine, compiled)
    radius = BlastRadius(rehearsal.rows_affected, count_rows(engine, shape))
    if radius.needs_confirmation and confirm_table_name != change_set.table_name:
        raise BadRequestError(
            f"This change affects {radius.explain()} To go ahead, send the table "
            f"name ({change_set.table_name}) as confirmation."
        )

    try:
        result = run_commit(engine, compiled, allow_conflicts=allow_conflicts)
    except (ConflictError, BadRequestError) as exc:
        # A failed attempt stays a draft: the edits are still valid, and the
        # person can retry once they have looked at what changed underneath.
        change_set.failure_reason = str(exc)
        db.commit()
        raise

    change_set.status = "committed"
    change_set.rows_affected = result.rows_affected
    change_set.committed_by_user_id = user_id
    change_set.failure_reason = None
    change_set.executed_sql = [
        {"sql": outcome.sql, "describes": outcome.describes, "rows": outcome.rows_affected}
        for outcome in result.outcomes
    ]
    change_set.committed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "writeback_committed",
        extra={
            "change_set_id": str(change_set.id),
            "table": change_set.table_name,
            "rows_affected": result.rows_affected,
            "statements": len(result.outcomes),
        },
    )
    return result


def migration_for(db: Session, change_set: ChangeSet) -> tuple[str, str]:
    _, _, compiled = _compile_for(db, change_set)
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in change_set.name).strip("_")
    filename = f"{change_set.table_name}_{slug[:60] or 'change'}.sql"
    title = f"{change_set.name} ({change_set.table_name})"
    return filename, export_as_migration(compiled, title=title)


# --------------------------------------------------------------------- private


def _shape_for(db: Session, change_set: ChangeSet) -> TableShape:
    engine = _engine_for(db, change_set.project_id, change_set.connection_id)
    return read_shape(
        engine,
        table=change_set.table_name,
        schema=change_set.table_schema,
        designated=list(change_set.designated_key or []) or None,
    )


def _compile_for(
    db: Session, change_set: ChangeSet
) -> tuple[Engine, TableShape, CompiledChange]:
    engine = _engine_for(db, change_set.project_id, change_set.connection_id)
    shape = read_shape(
        engine,
        table=change_set.table_name,
        schema=change_set.table_schema,
        designated=list(change_set.designated_key or []) or None,
    )
    edits = [
        _to_edit(EditInput(**{**row.payload_json, "kind": row.kind}))
        for row in sorted(change_set.edits, key=lambda row: (row.sequence, str(row.id)))
    ]
    if not edits:
        raise BadRequestError("This change set is empty, so there is nothing to apply.")
    return engine, shape, compile_change_set(engine, shape, edits)


def _require_draft(change_set: ChangeSet) -> None:
    if change_set.status in _TERMINAL:
        raise ConflictError(
            f"This change set is {change_set.status}, so it can no longer be modified."
        )


def _to_edit(payload: EditInput) -> Edit:
    return Edit(
        kind=EditKind(payload.kind),
        key=payload.key,
        column=payload.column,
        value=payload.value,
        # An explicit null and an absent field are different claims: one says
        # "it was null", the other says "nobody looked". Only the first is checked.
        previous=payload.previous if payload.has_previous else _UNRECORDED,
        values=payload.values,
        column_type=payload.column_type,
        new_name=payload.new_name,
    )
