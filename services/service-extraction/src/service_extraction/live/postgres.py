"""Change capture from PostgreSQL (D1, roadmap Phase 20).

Reads the database's own change log through a logical replication slot with
the `test_decoding` output plugin -- built into every PostgreSQL, no extension
to install -- in micro-batches over an ordinary connection with
`pg_logical_slot_peek_changes` / `pg_logical_slot_get_changes`. No replication
protocol client, no long-lived stream: every step is a plain SQL call that
can be retried.

Changes are peeked, stored as events, and only then consumed from the slot
up to the last line read -- the position from the same read that was stored,
never a second one, or a change committed in between would be consumed
without being stored. A crash between the two re-reads the same changes; each
one's position (a digest of its LSN, transaction and row) makes that a no-op,
so each change is saved once, by its id.

The snapshot reads every column as PostgreSQL's own text and converts it the
way `test_decoding` lines are converted, so a row from the snapshot and the
same row from a change look the same.

Requirements, checked and reported rather than assumed: `wal_level =
logical`, a free replication slot, and a role allowed to create one
(REPLICATION or superuser).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from service_extraction.live.base import Batch, ChangeCaptureKind, LiveError, Message, Outcome

PLUGIN = "test_decoding"
DEFAULT_BATCH = 500
#: `test_decoding` prints this for a large value an update did not change.
UNCHANGED_TOAST = "unchanged-toast-datum"

# The table may be quoted and contain spaces, so it is "everything up to the
# first `: INSERT|UPDATE|DELETE:`", not a run of non-spaces.
_HEADER = re.compile(r"^table (?P<table>.+?): (?P<op>INSERT|UPDATE|DELETE): ?(?P<rest>.*)$")
# `name[type]:value` where value is 'quoted' (with '' escaping), null, or bare.
_COLUMN = re.compile(r"(?P<name>\"[^\"]+\"|[^\s\[]+)\[(?P<type>[^\]]+)\]:(?P<value>'(?:[^']|'')*'|[^\s]+)")
_SLOT_SAFE = re.compile(r"[^a-z0-9_]+")


@dataclass
class Change:
    lsn: str
    xid: str
    op: str  # insert | update | delete
    table: str  # schema.table as test_decoding prints it
    row: dict[str, Any] = field(default_factory=dict)
    #: For UPDATE/DELETE with REPLICA IDENTITY, the old key columns.
    old_key: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    ok: bool
    reason: str
    wal_level: str | None = None


def typed(value: str | None, type_name: str) -> Any:
    """A column's text as the value it stands for: numbers, true or false, else the text."""
    if value is None:
        return None
    kind = type_name.lower()
    if kind in ("integer", "bigint", "smallint", "oid"):
        try:
            return int(value)
        except ValueError:
            return value
    if kind in ("numeric", "real", "double precision", "float4", "float8") or kind.startswith("numeric("):
        try:
            return float(value)
        except ValueError:
            return value
    if kind == "boolean":
        return value in ("true", "t")
    return value


def _coerce(value: str, type_name: str) -> Any:
    if value == "null":
        return None
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return typed(value, type_name)


def parse_test_decoding(line: str) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:
    """One `test_decoding` line into (op, table, row, old_key), or None for
    the lines that are not row changes (BEGIN, COMMIT, messages)."""
    match = _HEADER.match(line.strip())
    if not match:
        return None
    op = match.group("op").lower()
    table = match.group("table")
    rest = match.group("rest")
    old_key: dict[str, Any] = {}
    new_part = rest
    if "old-key:" in rest:
        old_text, _, new_text = rest.partition("new-tuple:")
        old_key = _columns(old_text.replace("old-key:", "", 1))
        new_part = new_text
    row = _columns(new_part) if new_part.strip() and new_part.strip() != "(no-tuple-data)" else {}
    return op, table, row, old_key


def _columns(text_part: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for match in _COLUMN.finditer(text_part):
        if match.group("value") == UNCHANGED_TOAST:
            continue  # not sent; applying the change keeps the value the row has
        name = match.group("name").strip('"')
        out[name] = _coerce(match.group("value"), match.group("type"))
    return out


def check_capability(engine: Engine) -> Capability:
    with engine.connect() as conn:
        wal_level = conn.execute(text("SHOW wal_level")).scalar()
        if wal_level != "logical":
            return Capability(
                False,
                f"wal_level is '{wal_level}'; change capture needs 'logical' "
                "(set it in postgresql.conf or start with `-c wal_level=logical`, then restart).",
                wal_level,
            )
        slots = conn.execute(text("SHOW max_replication_slots")).scalar()
        if slots is not None and int(slots) == 0:
            return Capability(False, "max_replication_slots is 0, so no slot can be made.", wal_level)
        return Capability(True, "logical decoding is available", wal_level)


def ensure_slot(engine: Engine, slot: str) -> bool:
    """Create the replication slot if it does not exist. True when created."""
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_replication_slots WHERE slot_name = :slot"), {"slot": slot}
        ).scalar()
        if exists:
            return False
        conn.execute(
            text("SELECT pg_create_logical_replication_slot(:slot, :plugin)"),
            {"slot": slot, "plugin": PLUGIN},
        )
        return True


def drop_slot(engine: Engine, slot: str) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_replication_slots WHERE slot_name = :slot"), {"slot": slot}
        ).scalar()
        if exists:
            conn.execute(text("SELECT pg_drop_replication_slot(:slot)"), {"slot": slot})


def peek_changes(engine: Engine, slot: str, *, limit: int = DEFAULT_BATCH,
                 tables: list[str] | None = None) -> tuple[list[Change], str | None]:
    """Read up to `limit` decoded lines WITHOUT consuming them.

    Returns the row changes (BEGIN/COMMIT skipped; `tables`, schema.table or
    table, narrows to the tables the source follows) and the LSN of the last
    line read, which is where to consume up to once they are stored. Both come
    from the same read: working the LSN out with a second peek let a change
    committed in between be consumed without ever being stored (D1).
    """
    changes, upto, _ = _peek(engine, slot, limit=limit, tables=tables)
    return changes, upto


def _peek(engine: Engine, slot: str, *, limit: int, tables: list[str] | None) -> tuple[list[Change], str | None, int]:
    wanted = {t.strip().lower() for t in (tables or []) if t.strip()}
    changes: list[Change] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT lsn::text, xid::text, data FROM pg_logical_slot_peek_changes(:slot, NULL, :limit)"),
            {"slot": slot, "limit": int(limit)},
        ).all()
    upto: str | None = None
    for lsn, xid, data in rows:
        upto = str(lsn)
        parsed = parse_test_decoding(str(data))
        if parsed is None:
            continue
        op, table, row, old_key = parsed
        if wanted and not _wanted(table, wanted):
            continue
        changes.append(Change(lsn=str(lsn), xid=str(xid), op=op, table=table, row=row, old_key=old_key))
    return changes, upto, len(rows)


def _wanted(table: str, wanted: set[str]) -> bool:
    plain_name = table.replace('"', "").lower()
    return plain_name in wanted or plain_name.split(".")[-1] in wanted or table.lower() in wanted


def consume_upto(engine: Engine, slot: str, lsn: str) -> int:
    """Advance the slot past `lsn` (inclusive), after the events are stored."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT count(*) FROM pg_logical_slot_get_changes(:slot, :upto, NULL)"),
            {"slot": slot, "upto": lsn},
        ).scalar()
    return int(rows or 0)


def change_position(change: Change) -> str:
    """A change's id: the same change read twice gets the same one."""
    key = f"{change.lsn}#{change.xid}#{change.op}#{json.dumps(change.row, sort_keys=True, default=str)}"
    return hashlib.sha1(key.encode()).hexdigest()[:24]


def slot_name_for(name: str, source_id: Any) -> str:
    base = _SLOT_SAFE.sub("_", f"pipewright_{name}".lower()).strip("_")[:44]
    return f"{base}_{str(source_id).replace('-', '')[:12]}"


def _split(table: str) -> tuple[str, str]:
    cleaned = table.strip()
    if "." in cleaned:
        schema, _, name = cleaned.partition(".")
    else:
        schema, name = "public", cleaned
    return schema.strip('"'), name.strip('"')


def _quoted(table: str) -> str:
    schema, name = _split(table)
    return f'"{schema.replace(chr(34), chr(34) * 2)}"."{name.replace(chr(34), chr(34) * 2)}"'


class PostgresChangeCapture(ChangeCaptureKind):
    key = "postgres_cdc"
    label = "PostgreSQL change capture"
    description = "Follow tables through PostgreSQL's change log and keep each one current."
    connection_types = ("postgresql",)
    guarantee = "message_id"
    guarantee_note = (
        "The replication slot is advanced only after the changes are saved; a change read again "
        "after a restart is recognised by its position."
    )
    verified_by = "test_live_change_capture.py"

    def _engine(self, settings: dict[str, Any]) -> Engine:
        from service_extraction.connectors import sql_database

        return sql_database.get_engine("postgresql", settings["connection"])

    def test(self, settings: dict[str, Any]) -> Outcome:
        try:
            engine = self._engine(settings)
            capability = check_capability(engine)
            if not capability.ok:
                return Outcome(False, capability.reason)
            details: list[str] = []
            with engine.connect() as conn:
                allowed = conn.execute(text(
                    "SELECT rolreplication OR rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
                if not allowed:
                    return Outcome(False, "This user cannot make a replication slot; it needs the REPLICATION "
                                          "attribute (ALTER ROLE ... REPLICATION) or to be a superuser.")
            for table in settings.get("tables") or []:
                keys = self.key_columns(settings, table)
                details.append(f"{table}: kept current by {', '.join(keys)}" if keys
                               else f"{table}: has no primary key, so only its changes are kept")
        except LiveError as exc:
            return Outcome(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - the database's own words are the answer
            return Outcome(False, f"Could not reach the database: {str(exc)[:300]}")
        return Outcome(True, "Logical decoding is on and this user can follow changes.", details)

    def start_position(self, settings: dict[str, Any]) -> dict[str, Any]:
        engine = self._engine(settings)
        capability = check_capability(engine)
        if not capability.ok:
            raise LiveError(capability.reason)
        created = ensure_slot(engine, settings["slot_name"])
        return {"slot": settings["slot_name"], "created": created}

    def key_columns(self, settings: dict[str, Any], table: str) -> list[str]:
        schema, name = _split(table)
        with self._engine(settings).connect() as conn:
            found = conn.execute(text(
                "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :name"), {"schema": schema, "name": name}).scalar()
            if found is None:
                raise LiveError(f"There is no table {schema}.{name} in this database.")
            rows = conn.execute(text(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
                "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = :oid AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"),
                {"oid": found}).all()
        return [str(row[0]) for row in rows]

    def snapshot(self, settings: dict[str, Any], table: str, *, chunk: int) -> Iterator[list[dict[str, Any]]]:
        schema, name = _split(table)
        engine = self._engine(settings)
        with engine.connect() as conn:
            columns = conn.execute(text(
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :name AND a.attnum > 0 AND NOT a.attisdropped "
                "ORDER BY a.attnum"), {"schema": schema, "name": name}).all()
        if not columns:
            raise LiveError(f"There is no table {schema}.{name} in this database.")
        keys = self.key_columns(settings, table)
        select_list = ", ".join(f'"{c.replace(chr(34), chr(34) * 2)}"::text' for c, _ in columns)
        order = (" ORDER BY " + ", ".join(f'"{k.replace(chr(34), chr(34) * 2)}"' for k in keys)) if keys else ""
        with engine.connect().execution_options(stream_results=True) as conn:
            result = conn.execute(text(f"SELECT {select_list} FROM {_quoted(table)}{order}"))
            while True:
                rows = result.fetchmany(chunk)
                if not rows:
                    break
                yield [
                    {column: typed(value, type_name) for (column, type_name), value in zip(columns, row, strict=True)}
                    for row in rows
                ]

    def read(self, settings: dict[str, Any], cursor: dict[str, Any] | None, *, limit: int) -> Batch:
        engine = self._engine(settings)
        capability = check_capability(engine)
        if not capability.ok:
            raise LiveError(capability.reason)
        slot = settings["slot_name"]
        created = ensure_slot(engine, slot)
        changes, upto, lines = _peek(engine, slot, limit=limit, tables=settings.get("tables"))
        messages = [
            Message(
                kind=change.op, table=change.table, position=change_position(change),
                payload={"lsn": change.lsn, "xid": change.xid, "row": change.row, "old_key": change.old_key},
            )
            for change in changes
        ]
        notes = ["Made the replication slot this source reads from."] if created else []
        return Batch(
            messages=messages,
            cursor={"lsn": upto} if upto else None,
            after_commit=(lambda: consume_upto(engine, slot, upto)) if upto else None,
            more=lines >= limit,
            notes=notes,
        )

    def forget(self, settings: dict[str, Any]) -> None:
        drop_slot(self._engine(settings), settings["slot_name"])
