"""The live schema, for browsing and for completing.

Read from the database rather than from anything the platform stored: a cached
schema that has drifted is worse than none, because autocomplete confidently
offers a column that was dropped last week.

Reflection is not free, though, so it is cached per engine for a short time --
long enough that typing does not re-inspect on every keystroke, short enough
that a column added in another tab shows up without anybody restarting.
"""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, inspect

from shared_python.errors import BadRequestError

#: How long a reflected schema is trusted. Autocomplete latency versus staleness.
CACHE_SECONDS = 60.0

#: Reflecting a warehouse with thousands of tables would hang the editor.
MAX_TABLES = 2_000


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool = False


@dataclass
class TableInfo:
    name: str
    schema: str | None
    kind: str = "table"
    columns: list[ColumnInfo] = field(default_factory=list)
    #: False until somebody expands it; column reflection is the expensive half.
    loaded: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass
class SchemaSnapshot:
    dialect: str
    default_schema: str | None
    tables: list[TableInfo] = field(default_factory=list)
    truncated: bool = False
    read_at: float = field(default_factory=time.monotonic)

    def find(self, name: str) -> TableInfo | None:
        """Match a table by qualified or bare name, case-insensitively."""
        wanted = name.strip().strip('"').strip("`").lower()
        for table in self.tables:
            if table.qualified.lower() == wanted or table.name.lower() == wanted:
                return table
        return None


#: Keyed on the engine itself, weakly. `id(engine)` would be simpler and wrong
#: twice over: the entry outlives the engine, and CPython reuses ids, so a new
#: engine can inherit a dead one's cached schema and autocomplete against the
#: wrong database.
_CACHE: "weakref.WeakKeyDictionary[Engine, SchemaSnapshot]" = weakref.WeakKeyDictionary()
_LOCK = threading.Lock()


def snapshot(engine: Engine, *, refresh: bool = False) -> SchemaSnapshot:
    """The database's tables, cached briefly per engine."""
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(engine)
        if cached is not None and not refresh and now - cached.read_at < CACHE_SECONDS:
            return cached

    try:
        inspector = inspect(engine)
        schemas = _schemas_to_read(inspector, engine.dialect.name)
        tables: list[TableInfo] = []
        truncated = False
        for schema in schemas:
            for name in inspector.get_table_names(schema=schema):
                tables.append(TableInfo(name=name, schema=schema, kind="table"))
            for name in inspector.get_view_names(schema=schema):
                tables.append(TableInfo(name=name, schema=schema, kind="view"))
            if len(tables) > MAX_TABLES:
                tables = tables[:MAX_TABLES]
                truncated = True
                break
    except Exception as exc:  # noqa: BLE001 - a driver error here is not actionable as-is
        raise BadRequestError(
            f"Could not read the schema of this connection: {exc}"
        ) from exc

    tables.sort(key=lambda table: (table.schema or "", table.name))
    fresh = SchemaSnapshot(
        dialect=engine.dialect.name,
        default_schema=_default_schema(inspector),
        tables=tables,
        truncated=truncated,
    )
    with _LOCK:
        _CACHE[engine] = fresh
    return fresh


def load_columns(engine: Engine, table: TableInfo) -> TableInfo:
    """Fill in one table's columns. Cheap enough to do on expand."""
    if table.loaded:
        return table
    try:
        inspector = inspect(engine)
        primary = set(
            (inspector.get_pk_constraint(table.name, schema=table.schema) or {}).get(
                "constrained_columns"
            )
            or []
        )
        columns = inspector.get_columns(table.name, schema=table.schema)
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(
            f"Could not read the columns of {table.qualified}: {exc}"
        ) from exc

    table.columns = [
        ColumnInfo(
            name=str(column["name"]),
            type=str(column.get("type", "")),
            nullable=bool(column.get("nullable", True)),
            primary_key=str(column["name"]) in primary,
        )
        for column in columns
    ]
    table.loaded = True
    return table


def forget(engine: Engine) -> None:
    """Drop the cached schema, after a DDL statement has changed it."""
    with _LOCK:
        _CACHE.pop(engine, None)


def _schemas_to_read(inspector: Any, dialect: str) -> list[str | None]:
    """Which schemas to walk.

    Postgres puts everything interesting in `public` and everything tedious in
    `pg_catalog` and `information_schema`; walking those would bury a user's
    twelve tables under six hundred system ones.
    """
    if dialect in ("sqlite", "mysql"):
        return [None]
    try:
        names = [
            name
            for name in inspector.get_schema_names()
            if name not in ("information_schema", "pg_catalog", "pg_toast")
            and not name.startswith("pg_temp")
        ]
    except Exception:  # noqa: BLE001 - a dialect without schema listing is fine
        return [None]
    return names or [None]


def _default_schema(inspector: Any) -> str | None:
    try:
        return inspector.default_schema_name
    except Exception:  # noqa: BLE001
        return None
