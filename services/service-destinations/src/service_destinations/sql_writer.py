"""Writing a dataset into a PostgreSQL or MySQL table.

Three ways to deliver, named the way the product names them:

- **replace**: drop the table and write it again, so it holds exactly this data.
- **append**: add the rows to what is there.
- **update**: "update matching rows" -- rows whose key columns match an
  existing row replace it, the rest are added. Done as delete-then-insert in
  one transaction rather than with each engine's own UPSERT syntax, so it
  works on a table with no unique constraint on the key (a table somebody
  else created) and reads the same on both engines.

A table this creates gets the key columns as its primary key when there are
any, so the database itself then refuses duplicates.

`plan_table` is the dry run: the columns and types that would be written,
computed without connecting, which is what the delivery preview shows.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Double,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    inspect,
    tuple_,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

from shared_python.errors import BadRequestError

ENGINES = {"postgres": "PostgreSQL", "mysql": "MySQL"}
MODES = ("replace", "append", "update")
_CHUNK = 1000
_RESERVED = {"select", "table", "where", "from", "group", "order", "insert", "update", "delete"}


@dataclass(frozen=True)
class ColumnPlan:
    name: str
    source: str
    #: boolean, integer, decimal, datetime or text.
    kind: str
    type_label: str
    key: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "type": self.type_label, "key": self.key}


@dataclass(frozen=True)
class TablePlan:
    destination_type: str
    table: str
    schema: str | None
    mode: str
    columns: tuple[ColumnPlan, ...]
    key_columns: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}" if self.schema else self.table


@dataclass
class WriteOutcome:
    rows_written: int
    rows_updated: int = 0
    rows_added: int = 0
    table_created: bool = False
    warnings: list[str] = field(default_factory=list)


def plural(count: int, noun: str) -> str:
    """"1 row", "3 rows", "1,200 rows"."""
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def validate_table_name(name: str, destination_type: str) -> str:
    name = (name or "").strip()
    limit = 63 if destination_type == "postgres" else 64
    if not name or len(name) > limit:
        raise BadRequestError(f"A table name is 1 to {limit} characters.")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise BadRequestError(
            "A table name starts with a letter or underscore and holds only letters, digits and underscores."
        )
    if name.lower() in _RESERVED:
        raise BadRequestError(f"“{name}” is a reserved word; choose another table name.")
    return name


def column_name(raw: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(raw).strip()) or "col"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:63]


def _column_names(columns: list[Any]) -> list[str]:
    """Column names safe for both engines, with collisions numbered."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in columns:
        base = column_name(raw)
        if base.lower() in seen:
            seen[base.lower()] += 1
            out.append(f"{base}_{seen[base.lower()]}"[:63])
        else:
            seen[base.lower()] = 0
            out.append(base)
    return out


_INFERRED_KINDS = {
    "boolean": "boolean",
    "integer": "integer",
    "floating": "decimal",
    "mixed-integer-float": "decimal",
    "decimal": "decimal",
    "datetime": "datetime",
    "datetime64": "datetime",
    "date": "datetime",
}


def column_kind(series: pd.Series) -> str:
    """boolean, integer, decimal, datetime or text.

    The platform's parser keeps each value's own type in an object column (an
    id column holds Python ints, not numpy ones), so the dtype alone says
    "text" for nearly everything. The values decide; a column with any text
    in it stays text, because a database will not take "n/a" as a number.
    """
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "decimal"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return _INFERRED_KINDS.get(pd.api.types.infer_dtype(series, skipna=True), "text")


_TYPE_LABELS = {
    "postgres": {"boolean": "boolean", "integer": "bigint", "decimal": "double precision",
                 "datetime": "timestamp with time zone", "text": "text", "key_text": "text"},
    "mysql": {"boolean": "boolean", "integer": "bigint", "decimal": "double",
              "datetime": "datetime", "text": "text", "key_text": "varchar(255)"},
}


def _sql_type(kind: str, destination_type: str, *, key: bool) -> Any:
    if kind == "boolean":
        return Boolean()
    if kind == "integer":
        return BigInteger()
    if kind == "decimal":
        return Double()
    if kind == "datetime":
        return DateTime(timezone=destination_type == "postgres")
    # MySQL cannot index an unbounded TEXT column, so a text key is VARCHAR(255).
    if key and destination_type == "mysql":
        return String(255)
    return Text()


def plan_table(
    frame: pd.DataFrame,
    *,
    destination_type: str,
    table: str,
    schema: str | None,
    mode: str,
    key_columns: list[str] | None,
) -> TablePlan:
    if destination_type not in ENGINES:
        raise BadRequestError("Tables can be delivered to PostgreSQL or MySQL.")
    if mode not in MODES:
        raise BadRequestError("Choose to replace the table, add the rows, or update matching rows.")
    table = validate_table_name(table, destination_type)
    names = _column_names(list(frame.columns))
    by_source = {str(source): name for source, name in zip(frame.columns, names)}
    keys: list[str] = []
    for requested in key_columns or []:
        if str(requested) not in by_source:
            raise BadRequestError(f"“{requested}” is not a column of this dataset.")
        keys.append(by_source[str(requested)])
    if mode == "update" and not keys:
        raise BadRequestError("Updating matching rows needs at least one key column to match on.")

    labels = _TYPE_LABELS[destination_type]
    columns = []
    for source, name in zip(frame.columns, names):
        kind = column_kind(frame[source])
        key = name in keys
        label = labels["key_text"] if (kind == "text" and key) else labels[kind]
        columns.append(ColumnPlan(name=name, source=str(source), kind=kind, type_label=label, key=key))

    notes: list[str] = []
    renamed = [f"{c.source} → {c.name}" for c in columns if c.source != c.name]
    if renamed:
        notes.append("Renamed for the database: " + ", ".join(renamed[:5]) + (" and more" if len(renamed) > 5 else "") + ".")
    if mode == "replace":
        notes.append("The table is dropped and written again, so it holds exactly this data.")
    elif mode == "append":
        notes.append("The rows are added to the table; a new table is created if there is none.")
    else:
        notes.append(
            "Rows whose " + ", ".join(keys) + " match an existing row replace it; the rest are added. "
            "A new table gets " + ", ".join(keys) + " as its primary key."
        )
    if mode == "update" and keys:
        sources = [column.source for column in columns if column.key]
        repeats = int(frame.duplicated(subset=sources, keep="last").sum())
        if repeats:
            notes.append(f"{plural(repeats, 'row')} repeat a key; the last of each is kept.")
    if destination_type == "mysql" and any(column_kind(frame[s]) == "datetime" for s in frame.columns):
        notes.append("MySQL keeps dates without a time zone, so times are written in UTC.")

    return TablePlan(
        destination_type=destination_type, table=table, schema=schema, mode=mode,
        columns=tuple(columns), key_columns=tuple(keys), notes=tuple(notes),
    )


def engine_for(destination_type: str, config: dict[str, Any]) -> Engine:
    if destination_type == "postgres":
        url = URL.create(
            "postgresql+psycopg", username=config["username"], password=config["password"],
            host=config["host"], port=int(config.get("port") or 5432), database=config["database"],
            query={"sslmode": str(config.get("ssl_mode") or "prefer")},
        )
        return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
    if destination_type == "mysql":
        url = URL.create(
            "mysql+pymysql", username=config["username"], password=config["password"],
            host=config["host"], port=int(config.get("port") or 3306), database=config["database"],
            query={"charset": "utf8mb4"},
        )
        return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
    raise BadRequestError("Tables can be delivered to PostgreSQL or MySQL.")


def _python(value: Any, destination_type: str) -> Any:
    """A value the database driver understands: no numpy scalars, no NaN."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    elif hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime) and destination_type == "mysql" and value.tzinfo is not None:
        from datetime import UTC

        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _records(frame: pd.DataFrame, names: list[str], destination_type: str) -> list[dict[str, Any]]:
    renamed = frame.copy()
    renamed.columns = names
    return [
        {key: _python(value, destination_type) for key, value in row.items()}
        for row in renamed.astype(object).to_dict(orient="records")
    ]


def _table(plan: TablePlan, metadata: MetaData) -> Table:
    columns = [
        Column(
            column.name,
            _sql_type(column.kind, plan.destination_type, key=column.key),
            primary_key=column.key,
            nullable=not column.key,
        )
        for column in plan.columns
    ]
    return Table(plan.table, metadata, *columns, schema=plan.schema)


def write_frame(frame: pd.DataFrame, *, plan: TablePlan, config: dict[str, Any]) -> WriteOutcome:
    names = [column.name for column in plan.columns]
    warnings: list[str] = []
    working = frame
    if plan.mode == "update":
        # Within one delivery the last row for a key wins, as it would if the
        # rows had arrived one after another.
        sources = {column.name: column.source for column in plan.columns}
        key_sources = [sources[key] for key in plan.key_columns]
        before = len(working)
        working = working.drop_duplicates(subset=key_sources, keep="last")
        if len(working) < before:
            warnings.append(f"{plural(before - len(working), 'row')} repeated a key; the last of each was kept.")
    records = _records(working, names, plan.destination_type)
    engine = engine_for(plan.destination_type, config)
    label = ENGINES[plan.destination_type]
    try:
        with engine.begin() as conn:
            exists = inspect(conn).has_table(plan.table, schema=plan.schema)
            created = False
            if plan.mode == "replace" or not exists:
                if exists:
                    Table(plan.table, MetaData(), schema=plan.schema, autoload_with=conn).drop(conn)
                table = _table(plan, MetaData())
                table.create(conn)
                created = True
            else:
                table = Table(plan.table, MetaData(), schema=plan.schema, autoload_with=conn)
                missing = [name for name in names if name not in table.c]
                if missing:
                    raise BadRequestError(
                        f"The table {plan.qualified} has no column {', '.join(missing)}. Replace the table "
                        "to change its columns, or leave those columns out in a recipe first."
                    )

            updated = 0
            if plan.mode == "update" and not created:
                key_columns = [table.c[key] for key in plan.key_columns]
                keys = [tuple(record[key] for key in plan.key_columns) for record in records]
                for start in range(0, len(keys), _CHUNK):
                    chunk = keys[start:start + _CHUNK]
                    if len(key_columns) == 1:
                        condition = key_columns[0].in_([key[0] for key in chunk])
                    else:
                        condition = tuple_(*key_columns).in_(chunk)
                    result = conn.execute(delete(table).where(condition))
                    updated += max(int(result.rowcount or 0), 0)

            for start in range(0, len(records), _CHUNK):
                conn.execute(table.insert(), records[start:start + _CHUNK])
    except BadRequestError:
        raise
    except SQLAlchemyError as exc:
        message = str(getattr(exc, "orig", exc)).splitlines()[0][:400]
        raise BadRequestError(f"{label} refused the delivery: {message}") from exc
    finally:
        engine.dispose()

    return WriteOutcome(
        rows_written=len(records),
        rows_updated=updated,
        rows_added=len(records) - updated,
        table_created=created,
        warnings=warnings,
    )
