"""Change data capture from PostgreSQL, the honest first slice of Phase 20.

Reads the database's own change log through a logical replication slot with
the `test_decoding` output plugin -- built into every PostgreSQL, no extension
to install -- polled in micro-batches over an ordinary connection with
`pg_logical_slot_peek_changes` / `pg_logical_slot_get_changes`. No replication
protocol client, no long-lived stream: seconds of latency, and every step is
a plain SQL call that can be retried.

Delivery is **at-least-once**: changes are peeked, stored as events, and only
then consumed from the slot up to the last stored LSN. A crash between the
two re-reads the same changes next time; the (source, position) uniqueness on
events makes that a no-op rather than a duplicate. Exactly-once is not
claimed because it is not provided.

Requirements the source must meet, checked and reported rather than assumed:
`wal_level = logical`, a free replication slot, and a role allowed to create
one (REPLICATION or superuser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

PLUGIN = "test_decoding"
DEFAULT_BATCH = 500

# The table may be quoted and contain spaces, so it is "everything up to the
# first `: INSERT|UPDATE|DELETE:`", not a run of non-spaces.
_HEADER = re.compile(r"^table (?P<table>.+?): (?P<op>INSERT|UPDATE|DELETE): ?(?P<rest>.*)$")
# `name[type]:value` where value is 'quoted' (with '' escaping), null, or bare.
_COLUMN = re.compile(r"(?P<name>\"[^\"]+\"|[^\s\[]+)\[(?P<type>[^\]]+)\]:(?P<value>'(?:[^']|'')*'|[^\s]+)")


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


def _coerce(value: str, type_name: str) -> Any:
    if value == "null":
        return None
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
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
        return value == "true"
    return value


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
        name = match.group("name").strip('"')
        out[name] = _coerce(match.group("value"), match.group("type"))
    return out


def check_capability(engine: Engine) -> Capability:
    with engine.connect() as conn:
        wal_level = conn.execute(text("SHOW wal_level")).scalar()
        if wal_level != "logical":
            return Capability(
                False,
                f"wal_level is '{wal_level}'; change data capture needs 'logical' "
                "(set it in postgresql.conf or `-c wal_level=logical` and restart).",
                wal_level,
            )
        slots = conn.execute(text("SHOW max_replication_slots")).scalar()
        if slots is not None and int(slots) == 0:
            return Capability(False, "max_replication_slots is 0; no slot can be created.", wal_level)
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
                 tables: list[str] | None = None) -> list[Change]:
    """Read up to `limit` decoded lines WITHOUT consuming them. Only row
    changes come back; BEGIN/COMMIT are skipped. `tables` (schema.table or
    table) narrows to the tables the source follows."""
    wanted = {t.strip().lower() for t in (tables or []) if t.strip()}
    changes: list[Change] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT lsn::text, xid::text, data FROM pg_logical_slot_peek_changes(:slot, NULL, :limit)"),
            {"slot": slot, "limit": int(limit)},
        ).all()
    for lsn, xid, data in rows:
        parsed = parse_test_decoding(str(data))
        if parsed is None:
            continue
        op, table, row, old_key = parsed
        bare = table.split(".")[-1].lower()
        if wanted and table.lower() not in wanted and bare not in wanted:
            continue
        changes.append(Change(lsn=str(lsn), xid=str(xid), op=op, table=table, row=row, old_key=old_key))
    return changes


def last_peeked_lsn(engine: Engine, slot: str, *, limit: int = DEFAULT_BATCH) -> str | None:
    """The LSN of the last line a peek of `limit` would return -- the point to
    consume up to, so filtered-out lines (other tables, BEGIN/COMMIT) do not
    keep the slot from advancing."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT max(lsn)::text FROM pg_logical_slot_peek_changes(:slot, NULL, :limit)"
            ),
            {"slot": slot, "limit": int(limit)},
        ).scalar()


def consume_upto(engine: Engine, slot: str, lsn: str) -> int:
    """Advance the slot past `lsn` (inclusive), after the events are stored."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT count(*) FROM pg_logical_slot_get_changes(:slot, :upto, NULL)"),
            {"slot": slot, "upto": lsn},
        ).scalar()
    return int(rows or 0)
