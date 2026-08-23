"""HTTP surface for write-back.

Editing a live table is the one thing in this platform that changes data the
platform does not own, so every route here is explicit about what it will do
before it does it: `/plan` rehearses, `/commit` applies, and nothing else writes.
"""

from __future__ import annotations

import uuid
from typing import Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_writeback import service
from service_writeback.identity import RowIdentity, TableShape
from service_writeback.models import ChangeSet
from service_writeback.read import MAX_PAGE
from service_writeback.schemas import (
    ChangeSetCreate,
    ChangeSetListResponse,
    ChangeSetRead,
    CommitRead,
    CommitRequest,
    EditsCreate,
    MigrationRead,
    PlanRead,
    RowIdentityRead,
    RowPageRead,
    StatementRead,
    TableShapeRead,
)


def _identity_read(identity: RowIdentity) -> RowIdentityRead:
    return RowIdentityRead(
        kind=identity.kind.value,
        columns=list(identity.columns),
        reason=identity.reason,
        caveat=identity.caveat,
        usable=identity.usable,
        durable=identity.durable,
    )


def _shape_read(shape: TableShape) -> TableShapeRead:
    return TableShapeRead(
        table=shape.table,
        table_schema=shape.schema,
        columns=list(shape.columns),
        nullable=sorted(shape.nullable),
        types={name: str(kind) for name, kind in shape.types.items()},
        identity=_identity_read(shape.identity),
        editable=shape.identity.usable,
    )


def _change_set_read(change_set: ChangeSet) -> ChangeSetRead:
    return ChangeSetRead(
        id=change_set.id,
        project_id=change_set.project_id,
        connection_id=change_set.connection_id,
        table_name=change_set.table_name,
        table_schema=change_set.table_schema,
        name=change_set.name,
        status=change_set.status,
        designated_key=list(change_set.designated_key or []),
        rows_affected=change_set.rows_affected,
        failure_reason=change_set.failure_reason,
        committed_at=change_set.committed_at,
        created_at=change_set.created_at,
        edits=[
            {
                "id": edit.id,
                "sequence": edit.sequence,
                "kind": edit.kind,
                "payload": edit.payload_json,
                "description": _describe(edit.kind, edit.payload_json),
            }
            for edit in sorted(change_set.edits, key=lambda row: (row.sequence, str(row.id)))
        ],
    )


def _describe(kind: str, payload: dict) -> str:
    """A one-line, human-readable version of an edit, for the review list."""
    column = payload.get("column") or ""
    key = ", ".join(f"{name}={value!r}" for name, value in (payload.get("key") or {}).items())
    if kind == "set_cell":
        return f"Set {column} to {payload.get('value')!r} where {key}"
    if kind == "insert_row":
        return f"Insert a row ({len(payload.get('values') or {})} value(s))"
    if kind == "delete_row":
        return f"Delete the row where {key}"
    if kind == "add_column":
        return f"Add column {column} ({payload.get('column_type') or 'text'})"
    if kind == "drop_column":
        return f"Drop column {column}"
    if kind == "rename_column":
        return f"Rename {column} to {payload.get('new_name')}"
    return kind


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["writeback"])
    base = "/projects/{project_id}/writeback"

    @router.get(f"{base}/tables/{{connection_id}}", response_model=TableShapeRead)
    def get_table_shape(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        table: str = Query(min_length=1, max_length=200),
        table_schema: str | None = Query(default=None, max_length=200),
        key: list[str] | None = Query(default=None),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TableShapeRead:
        """Can this table be edited, and by what key? Answered before any editing."""
        shape = service.describe_table(
            db,
            project_id,
            connection_id,
            table=table,
            schema=table_schema,
            designated=list(key) if key else None,
            user_id=current_user.id,
        )
        return _shape_read(shape)

    @router.get(f"{base}/rows/{{connection_id}}", response_model=RowPageRead)
    def get_rows(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        table: str = Query(min_length=1, max_length=200),
        table_schema: str | None = Query(default=None, max_length=200),
        key: list[str] | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=MAX_PAGE),
        offset: int = Query(default=0, ge=0),
        order_by: str | None = Query(default=None, max_length=200),
        descending: bool = Query(default=False),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RowPageRead:
        """Live rows in a stable order, so the same cell stays the same cell."""
        page = service.read_table_rows(
            db,
            project_id,
            connection_id,
            table=table,
            schema=table_schema,
            designated=list(key) if key else None,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
            user_id=current_user.id,
        )
        return RowPageRead(
            columns=page.columns,
            rows=page.rows,
            total=page.total,
            offset=page.offset,
            key_columns=page.key_columns,
        )

    @router.get(f"{base}/change-sets", response_model=ChangeSetListResponse)
    def list_change_sets(
        project_id: uuid.UUID,
        limit: int = Query(default=100, ge=1, le=500),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetListResponse:
        rows = service.list_change_sets(db, project_id, current_user.id, limit=limit)
        return ChangeSetListResponse(items=[_change_set_read(row) for row in rows])

    @router.post(
        f"{base}/change-sets",
        response_model=ChangeSetRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_change_set(
        project_id: uuid.UUID,
        payload: ChangeSetCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetRead:
        change_set = service.create_change_set(
            db,
            project_id,
            connection_id=payload.connection_id,
            table_name=payload.table_name,
            table_schema=payload.table_schema,
            name=payload.name,
            designated_key=payload.designated_key,
            user_id=current_user.id,
        )
        return _change_set_read(change_set)

    @router.get(f"{base}/change-sets/{{change_set_id}}", response_model=ChangeSetRead)
    def get_one(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetRead:
        return _change_set_read(
            service.get_change_set(db, project_id, change_set_id, current_user.id)
        )

    @router.post(f"{base}/change-sets/{{change_set_id}}/edits", response_model=ChangeSetRead)
    def post_edits(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        payload: EditsCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetRead:
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        return _change_set_read(service.add_edits(db, change_set, payload.edits))

    @router.delete(
        f"{base}/change-sets/{{change_set_id}}/edits/{{edit_id}}",
        response_model=ChangeSetRead,
    )
    def delete_edit(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        edit_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetRead:
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        return _change_set_read(service.remove_edit(db, change_set, edit_id))

    @router.post(f"{base}/change-sets/{{change_set_id}}/plan", response_model=PlanRead)
    def post_plan(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> PlanRead:
        """Rehearse inside a transaction that is always rolled back."""
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        planned = service.plan(db, change_set)
        compiled = planned["compiled"]
        result = planned["result"]
        radius = planned["blast_radius"]
        by_sql = {outcome.sql: outcome for outcome in result.outcomes}
        return PlanRead(
            identity=_identity_read(planned["shape"].identity),
            statements=[
                StatementRead(
                    sql=statement.sql,
                    describes=statement.describes,
                    kind=statement.kind,
                    expected_rows=statement.expected_rows,
                    actual_rows=(
                        by_sql[statement.sql].rows_affected if statement.sql in by_sql else None
                    ),
                    irreversible=statement.irreversible,
                )
                for statement in compiled.statements
            ],
            rows_affected=result.rows_affected,
            table_rows=planned["table_rows"],
            blast_radius=radius.explain(),
            needs_confirmation=radius.needs_confirmation,
            has_irreversible=compiled.has_irreversible,
            conflicts=[outcome.describes for outcome in result.conflicts],
            warnings=result.warnings,
            ddl_is_not_transactional=compiled.ddl_is_not_transactional,
        )

    @router.post(f"{base}/change-sets/{{change_set_id}}/commit", response_model=CommitRead)
    def post_commit(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        payload: CommitRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CommitRead:
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        result = service.commit_change_set(
            db,
            change_set,
            confirm_table_name=payload.confirm_table_name,
            allow_conflicts=payload.allow_conflicts,
            user_id=current_user.id,
        )
        return CommitRead(
            change_set_id=change_set.id,
            committed=result.committed,
            rows_affected=result.rows_affected,
            statements_run=len(result.outcomes),
            warnings=result.warnings,
        )

    @router.post(f"{base}/change-sets/{{change_set_id}}/discard", response_model=ChangeSetRead)
    def post_discard(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeSetRead:
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        return _change_set_read(service.discard(db, change_set))

    @router.get(f"{base}/change-sets/{{change_set_id}}/migration", response_model=MigrationRead)
    def get_migration(
        project_id: uuid.UUID,
        change_set_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MigrationRead:
        """The same SQL, as a file to review and run through change control."""
        change_set = service.get_change_set(db, project_id, change_set_id, current_user.id)
        filename, sql = service.migration_for(db, change_set)
        return MigrationRead(filename=filename, sql=sql)

    return router
