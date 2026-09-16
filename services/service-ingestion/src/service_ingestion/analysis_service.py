"""Analyse a file, find its saved spec, and remember a confirmed one.

This is the half of ingestion that happens *before* anything is stored. The
upload endpoint still exists and still works the way it always did; what is new
is that a client can ask "what is this file?" first, look at the answer, correct
it, and only then commit — which is what makes every inferred decision
reviewable instead of magic.

Nothing here writes a dataset. `analyse_upload` stores nothing at all;
`remember` stores only the spec.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger

from service_ingestion import spec as spec_module
from service_ingestion.models import IngestSpecRecord, column_fingerprint, name_pattern
from service_ingestion.sniff import analyse

logger = get_logger(__name__)

#: Rows shown in the preview. The Studio grid renders these before anything is
#: committed, which is the point: the decisions are visible against real rows.
PREVIEW_ROWS = 200


def analyse_upload(
    db: Session,
    *,
    project_id: uuid.UUID,
    file_name: str,
    content_type: str,
    payload: bytes,
    current_user: UserRead,
    spec_id: uuid.UUID | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Work out how to read a file. Stores nothing."""
    ensure_owned_project(db, project_id, current_user.id)
    if not payload:
        raise BadRequestError("The uploaded file is empty.")

    saved: IngestSpecRecord | None = None
    applied: spec_module.IngestSpec | None = None

    if spec_id is not None:
        saved = _get(db, project_id, spec_id)
        applied = spec_module.IngestSpec.from_dict(dict(saved.spec_json or {}))

    # A first pass with whatever the caller supplied, then -- if no spec was
    # named -- a look for one matching the columns this pass found. Two passes
    # rather than one because the columns are not known until the file is read,
    # and the fingerprint is the reliable key.
    result = analyse(
        payload,
        file_name=file_name,
        content_type=content_type,
        overrides={**(applied.overrides if applied else {}), **(overrides or {})},
    )

    suggestion: IngestSpecRecord | None = None
    if saved is None:
        suggestion = find_match(
            db,
            project_id=project_id,
            file_name=file_name,
            columns=[str(column) for column in result.frame.columns],
        )
        if suggestion is not None and not overrides:
            applied = spec_module.IngestSpec.from_dict(dict(suggestion.spec_json or {}))
            result = analyse(
                payload,
                file_name=file_name,
                content_type=content_type,
                overrides=applied.overrides,
            )

    derived = spec_module.from_analysis(result, derived_from=file_name)
    preview_frame = result.frame.head(PREVIEW_ROWS)

    converted = preview_frame
    notes: list[str] = []
    if not result.blocked_by:
        # Only convert when nothing is outstanding: applying a spec that is
        # missing a date format would raise, and the preview is exactly where
        # somebody is meant to see the question rather than an error.
        try:
            converted, notes = spec_module.apply(preview_frame, derived)
        except BadRequestError:
            converted, notes = preview_frame, []

    return {
        "file_name": file_name,
        "file_size_bytes": len(payload),
        "analysis": result.to_dict(),
        "spec": derived.to_dict(),
        "preview": _preview(converted),
        "conversion_notes": notes,
        "matched_spec": (
            {
                "id": str((saved or suggestion).id),
                "label": (saved or suggestion).label,
                "use_count": (saved or suggestion).use_count,
                "last_used_at": (
                    (saved or suggestion).last_used_at.isoformat()
                    if (saved or suggestion).last_used_at
                    else None
                ),
                "applied": saved is not None or bool(suggestion),
            }
            if (saved or suggestion)
            else None
        ),
        "questions": spec_module.unanswered(result),
    }


def find_match(
    db: Session, *, project_id: uuid.UUID, file_name: str, columns: list[str]
) -> IngestSpecRecord | None:
    """A saved spec for this kind of file, by columns first and name second."""
    fingerprint = column_fingerprint(columns)
    found = db.scalars(
        select(IngestSpecRecord)
        .where(
            IngestSpecRecord.project_id == project_id,
            IngestSpecRecord.column_fingerprint == fingerprint,
        )
        .order_by(IngestSpecRecord.use_count.desc())
        .limit(1)
    ).first()
    if found is not None:
        return found

    # The columns moved -- a field was added upstream -- but the file is still
    # last month's report under this month's name.
    return db.scalars(
        select(IngestSpecRecord)
        .where(
            IngestSpecRecord.project_id == project_id,
            IngestSpecRecord.name_pattern == name_pattern(file_name),
        )
        .order_by(IngestSpecRecord.use_count.desc())
        .limit(1)
    ).first()


def remember(
    db: Session,
    *,
    project_id: uuid.UUID,
    label: str,
    file_name: str,
    payload_spec: dict[str, Any],
    columns: list[str],
    current_user: UserRead,
) -> IngestSpecRecord:
    """Save a confirmed spec so the next file of this kind reuses it."""
    ensure_owned_project(db, project_id, current_user.id)
    parsed = spec_module.IngestSpec.from_dict(payload_spec)
    spec_module.validate(parsed)

    fingerprint = column_fingerprint(columns or [column.name for column in parsed.columns])
    pattern = name_pattern(file_name)

    existing = db.scalars(
        select(IngestSpecRecord).where(
            IngestSpecRecord.project_id == project_id,
            IngestSpecRecord.column_fingerprint == fingerprint,
            IngestSpecRecord.name_pattern == pattern,
        )
    ).first()

    if existing is not None:
        # Updating rather than adding a second: two specs for the same file
        # means the next upload picks one of them, and which one is arbitrary.
        existing.label = label.strip() or existing.label
        existing.spec_json = parsed.to_dict()
        existing.file_format = parsed.format
        db.flush()
        return existing

    record = IngestSpecRecord(
        project_id=project_id,
        label=label.strip() or f"How to read {file_name}",
        name_pattern=pattern,
        column_fingerprint=fingerprint,
        file_format=parsed.format,
        spec_json=parsed.to_dict(),
        created_by_user_id=current_user.id,
    )
    db.add(record)
    db.flush()
    return record


def record_use(db: Session, record: IngestSpecRecord) -> None:
    record.use_count += 1
    record.last_used_at = datetime.now(UTC)
    db.flush()


def list_specs(db: Session, *, project_id: uuid.UUID, current_user: UserRead) -> list[dict[str, Any]]:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(IngestSpecRecord)
        .where(IngestSpecRecord.project_id == project_id)
        .order_by(IngestSpecRecord.use_count.desc(), IngestSpecRecord.label)
    ).all()
    return [_render(record) for record in rows]


def delete_spec(
    db: Session, *, project_id: uuid.UUID, spec_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    record = _get(db, project_id, spec_id)
    db.delete(record)
    db.flush()


def _get(db: Session, project_id: uuid.UUID, spec_id: uuid.UUID) -> IngestSpecRecord:
    record = db.scalars(
        select(IngestSpecRecord).where(
            IngestSpecRecord.id == spec_id, IngestSpecRecord.project_id == project_id
        )
    ).first()
    if record is None:
        raise NotFoundError("Ingest spec not found.")
    return record


def _render(record: IngestSpecRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "label": record.label,
        "name_pattern": record.name_pattern,
        "column_fingerprint": record.column_fingerprint,
        "file_format": record.file_format,
        "spec": dict(record.spec_json or {}),
        "use_count": record.use_count,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _preview(frame: Any) -> dict[str, Any]:
    """A frame as JSON-safe rows, with the types it ended up with."""
    import pandas as pd

    safe = frame.copy()
    for column in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[column]):
            safe[column] = safe[column].astype(str)
    safe = safe.astype(object).where(pd.notna(safe), None)
    return {
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(frame[column].dtype) for column in frame.columns},
        "rows": safe.to_dict("records"),
    }
