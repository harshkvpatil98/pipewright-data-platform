"""Queries across sources over a real project (D2, O4): its connections and datasets.

`across.py` plans and runs; this finds what a query names and reads it:

- `connection.schema.table` (or `connection.table`, in the connection's own
  default schema) is a table in one of the project's database connections,
  matched by name; a name with spaces is written in double quotes, or typed
  in lower case with underscores (`shop_db`). Its statistics come from
  `service_extraction.table_statistics`.
- `datasets."Name"` is one of the project's datasets, read as the person
  running the query may see it: denied columns do not exist for them, and a
  dataset whose rows a policy filters has no statistics to estimate from.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, UNKNOWN, PWType
from shared_python.types.lattice import timestamp

from service_workbench import across

#: How long one source may take over its part of a query.
SOURCE_TIMEOUT_SECONDS = 120
_SQL_TYPES = ("postgresql", "mysql", "sqlite")


def _pw_type(declared: str) -> PWType:
    word = (declared or "").lower()
    if "int" in word:
        return INT64
    if any(part in word for part in ("char", "text", "string", "uuid", "json")):
        return STRING
    if any(part in word for part in ("num", "dec", "float", "double", "real", "money")):
        return FLOAT64
    if "bool" in word:
        return BOOLEAN
    if "timestamp" in word or "datetime" in word:
        return timestamp()
    if "date" in word:
        return DATE
    return UNKNOWN


_PROFILE_TYPES = {"int": INT64, "float": FLOAT64, "decimal": FLOAT64, "string": STRING, "bool": BOOLEAN,
                  "datetime": timestamp(), "date": DATE}


class ProjectCatalogue:
    def __init__(self, db: Session, project_id: uuid.UUID, user: Any, storage_backend: Any) -> None:
        from service_enterprise.policy_view import Reader

        self.db = db
        self.project_id = project_id
        self.storage = storage_backend
        self.reader = Reader.for_user(db, project_id, user)
        self._connections: dict[str, Any] = {}

    # -- finding tables

    def table(self, parts: list[str]) -> across.Table:
        if len(parts) == 2 and parts[0].lower() == "datasets":
            return self._dataset(parts[1])
        if len(parts) == 1:
            raise BadRequestError(f"Say where {parts[0]!r} is: connection.schema.table, or datasets.\"Name\".")
        connection = self._connection(parts[0])
        schema, name = (parts[1], parts[2]) if len(parts) == 3 else (None, parts[1])
        return self._connection_table(connection, schema, name)

    def _dataset(self, name: str) -> across.Table:
        from service_datasets.models import Dataset
        from service_enterprise.policy_view import view_for
        from shared_python.statistics import from_profile

        found = list(self.db.scalars(select(Dataset).where(Dataset.project_id == self.project_id)).all())
        dataset = next((d for d in found if d.name == name), None) or next(
            (d for d in found if d.name.lower() == name.lower()), None)
        if dataset is None:
            raise BadRequestError(f'No dataset in this project is called "{name}".')
        if not dataset.file_path:
            raise BadRequestError(f'The dataset "{dataset.name}" has no saved data to read.')
        view = view_for(self.db, self.project_id, dataset.id, self.reader)
        schema = dataset.schema_json or {}
        types = {str(c.get("name")): str(c.get("inferred_type") or "") for c in schema.get("columns") or []
                 if isinstance(c, dict)}
        names = view.visible_columns([str(n) for n in schema.get("ordered_columns") or types])
        stats = None if view.filters_rows else from_profile(view.profile(dataset.profile_json))
        return across.Table(label=f'datasets."{dataset.name}"', kind="dataset", origin=f"dataset:{dataset.id}",
                            name=dataset.name, schema=None,
                            columns=[(n, _PROFILE_TYPES.get(types.get(n, ""), UNKNOWN)) for n in names], stats=stats)

    def _connection(self, name: str):
        from service_extraction.models import ExtractionConnection

        connections = list(self.db.scalars(select(ExtractionConnection).where(
            ExtractionConnection.project_id == self.project_id,
            ExtractionConnection.connector_type.in_(_SQL_TYPES))).all())
        wanted = name.lower()
        connection = next((c for c in connections if c.name == name), None) or next(
            (c for c in connections if c.name.lower() == wanted or across.plain_name(c.name) == wanted), None)
        if connection is None:
            known = ", ".join(sorted(c.name for c in connections)) or "none yet"
            raise BadRequestError(f"No database connection in this project is called {name!r} (there are: {known}).")
        return connection

    def _config(self, connection) -> dict[str, Any]:
        from service_extraction.connector_sources import secret_fields
        from shared_python.security.config_crypto import decrypt_sensitive_fields

        return decrypt_sensitive_fields(dict(connection.config_json or {}), secret_fields(connection.connector_type))

    def _connection_table(self, connection, schema: str | None, name: str) -> across.Table:
        from service_extraction import table_statistics
        from service_extraction.connectors import sql_database

        config = self._config(connection)
        schema = schema or config.get("schema") or None
        try:
            columns = sql_database.list_columns(connection.connector_type, config, table=name, schema=schema)
        except BadRequestError as exc:
            raise BadRequestError(f"{connection.name} has no table {name!r} it can read ({exc.detail}).") from exc
        self._connections[str(connection.id)] = connection
        try:
            stats = table_statistics.for_table(self.db, connection, schema, name)
        except Exception:  # noqa: BLE001 - statistics improve a plan; a query runs without them
            stats = None
        label = f"{connection.name}.{schema + '.' if schema else ''}{name}"
        return across.Table(label=label, kind="connection", origin=f"connection:{connection.id}", name=name,
                            schema=schema, columns=[(c.name, _pw_type(c.data_type)) for c in columns],
                            dialect=across._DIALECTS[connection.connector_type], stats=stats)

    # -- reading

    def fetch(self, table_origin: str, dialect: str, sql: str, max_rows: int) -> pd.DataFrame:
        from service_extraction.connectors import sql_database
        from service_workbench.execute import _apply_timeout

        from sqlalchemy.exc import SQLAlchemyError

        connection = self._connections[table_origin.split(":", 1)[1]]
        engine = sql_database.get_engine(connection.connector_type, self._config(connection))
        frames, collected = [], 0
        try:
            # The connection's implicit transaction holds PostgreSQL's SET LOCAL timeout; it is
            # rolled back on the way out, which a read never minds.
            with engine.connect() as conn:
                _apply_timeout(conn, engine.dialect.name, SOURCE_TIMEOUT_SECONDS)
                # Only the query streams: on PostgreSQL a streamed statement is a server-side
                # cursor, which a SET cannot be.
                statement = text(sql).execution_options(stream_results=True)
                for chunk in pd.read_sql_query(statement, conn, chunksize=50_000):
                    frames.append(chunk)
                    collected += len(chunk)
                    if collected >= max_rows:
                        # Past the limit the query stops; a MySQL result would be read to its end first.
                        if connection.connector_type == "mysql":
                            sql_database.abandon_unread_result(conn)
                        break
        except SQLAlchemyError as exc:
            raise BadRequestError(
                f"{connection.name} could not run its part of the query: {sql_database._safe_error(exc)}") from exc
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    def read_dataset(self, table_origin: str) -> pd.DataFrame:
        from service_transformations.dataset_access import build_step_context

        context = build_step_context(self.db, project_id=self.project_id, storage_backend=self.storage,
                                     reader=self.reader)
        return context.load_dataset(table_origin.split(":", 1)[1])


def run(db: Session, project_id: uuid.UUID, *, sql: str, user: Any, storage_backend: Any) -> across.Outcome:
    """Run a query across sources, and keep it in the workbench's history like any other."""
    from service_projects.contracts import ensure_owned_project
    from service_workbench.models import QueryRun

    ensure_owned_project(db, project_id, user.id)
    started = time.perf_counter()
    error: str | None = None
    outcome: across.Outcome | None = None
    try:
        outcome = across.run(sql, ProjectCatalogue(db, project_id, user, storage_backend))
        return outcome
    except BadRequestError as exc:
        error = str(exc.detail)
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        db.rollback()
        db.add(QueryRun(
            project_id=project_id, connection_id=None, saved_query_id=None, sql=sql[:100_000], statement_count=1,
            wrote=False, succeeded=error is None,
            duration_ms=outcome.duration_ms if outcome else round((time.perf_counter() - started) * 1000, 1),
            rows_returned=outcome.row_count if outcome else 0, rows_affected=0, error=(error or "")[:4_000] or None,
            run_by_user_id=getattr(user, "id", None)))
        db.commit()
