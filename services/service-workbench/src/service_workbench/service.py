"""Orchestration for the workbench.

Thin by design: the interesting decisions live in `safety`, `execute`,
`sandbox` and `notebook`, and this module is what joins them to the database and
to the person making the request.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger
from service_projects.contracts import ensure_owned_project

from service_workbench import sandbox
from service_workbench.execute import ScriptResult, explain as explain_sql, run_script
from service_workbench.models import Notebook, NotebookCell, QueryRun, SavedQuery
from service_workbench.notebook import Cell, Namespace, NotebookResult, run_notebook
from service_workbench.safety import SessionPolicy, check, policy_for
from service_workbench.schema_tree import forget, load_columns, snapshot
from service_workbench.sql_text import parse

logger = get_logger(__name__)

#: Injected by the gateway, exactly as write-back does it, so this service
#: depends on no connector package and no database driver.
_engine_resolver: Callable[[Session, uuid.UUID, uuid.UUID], Engine] | None = None


def register_engine_resolver(
    resolver: Callable[[Session, uuid.UUID, uuid.UUID], Engine],
) -> None:
    global _engine_resolver
    _engine_resolver = resolver


def engine_for(db: Session, project_id: uuid.UUID, connection_id: uuid.UUID | None) -> Engine | None:
    if connection_id is None:
        return None
    if _engine_resolver is None:
        raise BadRequestError(
            "The workbench is not available: no database connection provider is registered."
        )
    return _engine_resolver(db, project_id, connection_id)


# ------------------------------------------------------------------- running


def run(
    db: Session,
    project_id: uuid.UUID,
    *,
    connection_id: uuid.UUID,
    sql: str,
    parameters: dict[str, Any] | None,
    allow_writes: bool,
    allow_ddl: bool,
    user: Any,
    saved_query_id: uuid.UUID | None = None,
) -> tuple[ScriptResult, SessionPolicy]:
    """Run a script and record that it happened."""
    project = ensure_owned_project(db, project_id, user.id)
    engine = engine_for(db, project_id, connection_id)
    if engine is None:
        raise BadRequestError("Choose a database connection before running anything.")

    policy = policy_for(
        role=getattr(user, "role", None),
        environment=getattr(project, "environment", "development") or "development",
        requested_writes=allow_writes,
        requested_ddl=allow_ddl,
    )
    if allow_writes and not policy.allow_writes:
        raise BadRequestError(
            "Write mode needs the admin role. Writing to a source database by "
            "hand bypasses every review the rest of the platform applies, so it "
            "is not something an editor role carries."
        )

    script = parse(sql)
    try:
        result = run_script(engine, sql, policy=policy, parameters=parameters)
    except Exception as exc:
        _record(
            db,
            project_id=project_id,
            connection_id=connection_id,
            saved_query_id=saved_query_id,
            sql=sql,
            script=script,
            result=None,
            error=str(exc),
            user=user,
        )
        raise

    if any(statement.kind.value == "ddl" for statement in script.statements) and result.committed:
        # The schema just changed, so the cached one is wrong -- and the next
        # thing anybody does is autocomplete against it.
        forget(engine)

    _record(
        db,
        project_id=project_id,
        connection_id=connection_id,
        saved_query_id=saved_query_id,
        sql=sql,
        script=script,
        result=result,
        error=result.first_error,
        user=user,
    )
    return result, policy


def preview_policy(
    db: Session,
    project_id: uuid.UUID,
    *,
    sql: str,
    allow_writes: bool,
    allow_ddl: bool,
    user: Any,
) -> dict[str, Any]:
    """What would happen if this ran, without running it."""
    project = ensure_owned_project(db, project_id, user.id)
    script = parse(sql)
    policy = policy_for(
        role=getattr(user, "role", None),
        environment=getattr(project, "environment", "development") or "development",
        requested_writes=allow_writes,
        requested_ddl=allow_ddl,
    )
    verdict = check(script, policy)
    return {
        "statements": script.statements,
        "parameters": script.parameters,
        "policy": policy,
        "verdict": verdict,
    }


def explain(
    db: Session,
    project_id: uuid.UUID,
    *,
    connection_id: uuid.UUID,
    sql: str,
    parameters: dict[str, Any] | None,
    user: Any,
):
    ensure_owned_project(db, project_id, user.id)
    engine = engine_for(db, project_id, connection_id)
    if engine is None:
        raise BadRequestError("Choose a database connection first.")
    return explain_sql(engine, sql, parameters)


def _record(
    db: Session,
    *,
    project_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    saved_query_id: uuid.UUID | None,
    sql: str,
    script: Any,
    result: ScriptResult | None,
    error: str | None,
    user: Any,
) -> None:
    """Write history. Never the results -- see `models.QueryRun`."""
    db.add(
        QueryRun(
            project_id=project_id,
            connection_id=connection_id,
            saved_query_id=saved_query_id,
            sql=sql[:100_000],
            statement_count=len(script.statements),
            wrote=script.writes,
            succeeded=error is None,
            duration_ms=result.duration_ms if result else 0.0,
            rows_returned=sum(s.row_count for s in result.statements) if result else 0,
            rows_affected=sum(s.rows_affected or 0 for s in result.statements) if result else 0,
            error=(error or "")[:4_000] or None,
            run_by_user_id=getattr(user, "id", None),
        )
    )
    if saved_query_id is not None:
        saved = db.get(SavedQuery, saved_query_id)
        if saved is not None:
            saved.run_count += 1
            saved.last_run_at = datetime.now(timezone.utc)
    db.commit()


def history(
    db: Session, project_id: uuid.UUID, user: Any, *, limit: int = 50, mine_only: bool = False
) -> list[QueryRun]:
    ensure_owned_project(db, project_id, user.id)
    query = select(QueryRun).where(QueryRun.project_id == project_id)
    if mine_only:
        query = query.where(QueryRun.run_by_user_id == user.id)
    return list(
        db.scalars(query.order_by(QueryRun.created_at.desc(), QueryRun.id).limit(limit)).all()
    )


# ------------------------------------------------------------ saved queries


def list_saved(db: Session, project_id: uuid.UUID, user: Any) -> list[SavedQuery]:
    ensure_owned_project(db, project_id, user.id)
    return list(
        db.scalars(
            select(SavedQuery)
            .where(SavedQuery.project_id == project_id)
            .order_by(SavedQuery.name)
        ).all()
    )


def get_saved(db: Session, project_id: uuid.UUID, saved_id: uuid.UUID, user: Any) -> SavedQuery:
    ensure_owned_project(db, project_id, user.id)
    saved = db.get(SavedQuery, saved_id)
    if saved is None or saved.project_id != project_id:
        raise NotFoundError("That saved query does not exist in this project.")
    return saved


def save(
    db: Session,
    project_id: uuid.UUID,
    user: Any,
    *,
    name: str,
    sql: str,
    description: str | None,
    connection_id: uuid.UUID | None,
    parameters: dict[str, Any] | None,
) -> SavedQuery:
    ensure_owned_project(db, project_id, user.id)
    script = parse(sql)  # refuse to save something that will not parse
    existing = db.scalar(
        select(SavedQuery).where(
            SavedQuery.project_id == project_id, SavedQuery.name == name
        )
    )
    if existing is not None:
        raise ConflictError(f"This project already has a saved query called {name!r}.")

    saved = SavedQuery(
        project_id=project_id,
        connection_id=connection_id,
        name=name,
        description=description,
        sql=sql,
        # Declared so somebody who did not write it can run it.
        parameters_json={key: (parameters or {}).get(key) for key in script.parameters},
        created_by_user_id=user.id,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


def update_saved(
    db: Session, project_id: uuid.UUID, saved_id: uuid.UUID, user: Any, **changes: Any
) -> SavedQuery:
    saved = get_saved(db, project_id, saved_id, user)
    if "sql" in changes and changes["sql"] is not None:
        script = parse(changes["sql"])
        saved.sql = changes["sql"]
        saved.parameters_json = {
            key: saved.parameters_json.get(key) for key in script.parameters
        }
    for field in ("name", "description", "connection_id"):
        if changes.get(field) is not None:
            setattr(saved, field, changes[field])
    if changes.get("parameters") is not None:
        saved.parameters_json = {
            key: changes["parameters"].get(key, value)
            for key, value in saved.parameters_json.items()
        }
    db.commit()
    db.refresh(saved)
    return saved


def delete_saved(db: Session, project_id: uuid.UUID, saved_id: uuid.UUID, user: Any) -> None:
    saved = get_saved(db, project_id, saved_id, user)
    db.delete(saved)
    db.commit()


# ---------------------------------------------------------------- schema tree


def browse(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    user: Any,
    *,
    table: str | None = None,
    refresh: bool = False,
):
    ensure_owned_project(db, project_id, user.id)
    engine = engine_for(db, project_id, connection_id)
    if engine is None:
        raise BadRequestError("Choose a database connection first.")
    found = snapshot(engine, refresh=refresh)
    if table:
        entry = found.find(table)
        if entry is None:
            raise NotFoundError(f"There is no table called {table!r} on this connection.")
        load_columns(engine, entry)
    return found


def completions(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    user: Any,
    *,
    sql: str,
    offset: int | None,
    limit: int,
):
    from service_workbench.completion import complete, tables_in_scope

    ensure_owned_project(db, project_id, user.id)
    engine = engine_for(db, project_id, connection_id)
    if engine is None:
        raise BadRequestError("Choose a database connection first.")
    found = snapshot(engine)
    # Only the tables the statement actually names get their columns read.
    # Reflecting every table on every keystroke is how autocomplete becomes the
    # slowest thing in the editor.
    for name in dict.fromkeys(tables_in_scope(sql, offset).values()):
        entry = found.find(name)
        if entry is not None and not entry.loaded:
            try:
                load_columns(engine, entry)
            except BadRequestError:
                continue
    return complete(found, sql, offset, limit=limit)


# ------------------------------------------------------------------ notebooks


def list_notebooks(db: Session, project_id: uuid.UUID, user: Any) -> list[Notebook]:
    ensure_owned_project(db, project_id, user.id)
    return list(
        db.scalars(
            select(Notebook)
            .where(Notebook.project_id == project_id)
            .order_by(Notebook.updated_at.desc())
        ).all()
    )


def get_notebook(db: Session, project_id: uuid.UUID, notebook_id: uuid.UUID, user: Any) -> Notebook:
    ensure_owned_project(db, project_id, user.id)
    found = db.get(Notebook, notebook_id)
    if found is None or found.project_id != project_id:
        raise NotFoundError("That notebook does not exist in this project.")
    return found


def create_notebook(
    db: Session,
    project_id: uuid.UUID,
    user: Any,
    *,
    name: str,
    description: str | None,
    connection_id: uuid.UUID | None,
    cells: list[dict[str, Any]] | None,
) -> Notebook:
    ensure_owned_project(db, project_id, user.id)
    found = Notebook(
        project_id=project_id,
        connection_id=connection_id,
        name=name,
        description=description,
        created_by_user_id=user.id,
    )
    db.add(found)
    db.flush()
    _replace_cells(db, found, cells or [])
    db.commit()
    db.refresh(found)
    return found


def update_notebook(
    db: Session, project_id: uuid.UUID, notebook_id: uuid.UUID, user: Any, **changes: Any
) -> Notebook:
    found = get_notebook(db, project_id, notebook_id, user)
    for field in ("name", "description", "connection_id"):
        if changes.get(field) is not None:
            setattr(found, field, changes[field])
    if changes.get("cells") is not None:
        _replace_cells(db, found, changes["cells"])
    db.commit()
    db.refresh(found)
    return found


def delete_notebook(db: Session, project_id: uuid.UUID, notebook_id: uuid.UUID, user: Any) -> None:
    found = get_notebook(db, project_id, notebook_id, user)
    db.delete(found)
    db.commit()


def _replace_cells(db: Session, notebook: Notebook, cells: list[dict[str, Any]]) -> None:
    """Cells are saved whole. A notebook is one document, not a set of rows."""
    db.execute(delete(NotebookCell).where(NotebookCell.notebook_id == notebook.id))
    for position, raw in enumerate(cells):
        # Validated through the same class the runner uses, so a notebook cannot
        # be saved in a state that will not run.
        Cell(
            kind=str(raw.get("kind", "sql")),
            source=str(raw.get("source", "")),
            output_name=raw.get("output_name") or None,
            config=raw.get("config") or {},
            position=position,
        )
        db.add(
            NotebookCell(
                notebook_id=notebook.id,
                position=position,
                kind=str(raw.get("kind", "sql")),
                source=str(raw.get("source", "")),
                output_name=raw.get("output_name") or None,
                config_json=raw.get("config") or {},
            )
        )
    db.flush()


def run_notebook_for(
    db: Session,
    project_id: uuid.UUID,
    notebook_id: uuid.UUID,
    user: Any,
    *,
    allow_writes: bool = False,
    only_to: int | None = None,
) -> NotebookResult:
    found = get_notebook(db, project_id, notebook_id, user)
    project = ensure_owned_project(db, project_id, user.id)
    engine = engine_for(db, project_id, found.connection_id)

    cells = [
        Cell(
            kind=row.kind,
            source=row.source,
            output_name=row.output_name,
            config=row.config_json or {},
            position=row.position,
        )
        for row in sorted(found.cells, key=lambda row: row.position)
        if only_to is None or row.position <= only_to
    ]
    policy = policy_for(
        role=getattr(user, "role", None),
        environment=getattr(project, "environment", "development") or "development",
        requested_writes=allow_writes,
        requested_ddl=False,
    )
    return run_notebook(cells, engine=engine, policy=policy, namespace=Namespace())


def sandbox_status() -> dict[str, Any]:
    return sandbox.describe()
