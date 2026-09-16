"""Running a script and reporting what each statement did.

Three decisions shape this module:

* **One connection, one transaction, for the whole script.** A script that
  half-succeeds is the worst outcome -- worse than one that fails, because
  nobody knows which half. Reads are harmless either way; writes roll back
  together unless the script manages its own transaction.
* **Results are bounded and say so.** A workbench is for looking. A `SELECT *`
  against a billion-row table must return a page and a note, not stream until
  something falls over.
* **Every statement is timed, including the ones that failed.** "It was slow"
  and "it was slow and then it failed" are different problems.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from shared_python.errors import BadRequestError
from shared_python.logging import get_logger

from service_workbench.safety import SessionPolicy, enforce
from service_workbench.sql_text import Script, Statement, StatementKind, parse

logger = get_logger(__name__)

#: Hard ceiling on rows held in memory per statement, whatever the policy says.
MAX_ROW_LIMIT = 10_000

#: How each dialect is told to stop. Set per connection, before anything runs.
#:
#: This is the difference between a workbench and a way to take a database down:
#: without it, one careless join holds a connection and a server-side query for
#: as long as the database is willing to keep going, and closing the browser tab
#: does not stop it. SQLite is absent because it has no such statement -- it
#: gets an interrupt from the client side instead, below.
_TIMEOUT_SQL = {
    "postgresql": "SET LOCAL statement_timeout = {ms}",
    "postgres": "SET LOCAL statement_timeout = {ms}",
    "mysql": "SET SESSION max_execution_time = {ms}",
    "duckdb": None,
    "sqlite": None,
}


def _apply_timeout(connection: Any, dialect: str, seconds: int) -> str | None:
    """Ask the database to stop by itself. Returns a warning if it cannot."""
    template = _TIMEOUT_SQL.get(dialect, "")
    if template:
        try:
            connection.execute(text(template.format(ms=max(1, seconds) * 1000)))
            return None
        except (DBAPIError, SQLAlchemyError) as exc:
            return (
                f"This connection would not accept a {seconds}s statement timeout "
                f"({_readable(exc)}), so a long query will run to completion."
            )
    if dialect == "sqlite":
        # SQLite has no statement timeout; the client interrupts instead, which
        # this process can only do while it is not blocked in the driver. Said
        # plainly rather than left as an unstated gap.
        return None
    return (
        f"{dialect} has no statement timeout this platform knows how to set, so "
        "a long query will run to completion."
    )


@dataclass
class StatementResult:
    """What one statement produced."""

    index: int
    sql: str
    summary: str
    kind: str
    duration_ms: float
    #: Present for statements that return rows.
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Rows the database returned, before the display cap.
    row_count: int = 0
    truncated: bool = False
    #: Present for statements that change rows.
    rows_affected: int | None = None
    error: str | None = None
    #: True when the statement never ran because an earlier one failed.
    skipped: bool = False

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.skipped


@dataclass
class ScriptResult:
    statements: list[StatementResult] = field(default_factory=list)
    duration_ms: float = 0.0
    committed: bool = False
    warnings: list[str] = field(default_factory=list)
    policy: str = "read-only"

    @property
    def failed(self) -> bool:
        return any(result.error for result in self.statements)

    @property
    def first_error(self) -> str | None:
        for result in self.statements:
            if result.error:
                return f"Statement {result.index}: {result.error}"
        return None


def run_script(
    engine: Engine,
    sql: str,
    *,
    policy: SessionPolicy | None = None,
    parameters: dict[str, Any] | None = None,
) -> ScriptResult:
    """Parse, check, and run a script, reporting per statement."""
    active = policy or SessionPolicy()
    script = parse(sql)
    verdict = enforce(script, active)
    _require_parameters(script, parameters or {})

    result = ScriptResult(warnings=list(verdict.warnings), policy=active.describe())
    limit = max(1, min(active.row_limit, MAX_ROW_LIMIT))
    started = time.perf_counter()

    connection = engine.connect()
    transaction = connection.begin()
    try:
        note = _apply_timeout(connection, engine.dialect.name.lower(), active.timeout_seconds)
        if note:
            result.warnings.append(note)
        for statement in script.statements:
            outcome = _run_one(connection, statement, parameters or {}, limit)
            result.statements.append(outcome)
            if outcome.error:
                # Everything after a failure is reported as skipped rather than
                # silently missing: "9 of 12 ran" is the fact people need.
                for remaining in script.statements[statement.index :]:
                    result.statements.append(
                        StatementResult(
                            index=remaining.index,
                            sql=remaining.sql,
                            summary=remaining.summary,
                            kind=remaining.kind.value,
                            duration_ms=0.0,
                            skipped=True,
                        )
                    )
                break

        if result.failed:
            transaction.rollback()
        else:
            transaction.commit()
            result.committed = True
    except Exception:
        transaction.rollback()
        raise
    finally:
        if not connection.closed:
            connection.close()

    result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    if script.writes:
        logger.info(
            "workbench_script_ran",
            extra={
                "statements": len(script.statements),
                "writes": sum(1 for s in script.statements if s.kind.writes),
                "committed": result.committed,
                "duration_ms": result.duration_ms,
            },
        )
    return result


def _run_one(
    connection: Any, statement: Statement, parameters: dict[str, Any], limit: int
) -> StatementResult:
    outcome = StatementResult(
        index=statement.index,
        sql=statement.sql,
        summary=statement.summary,
        kind=statement.kind.value,
        duration_ms=0.0,
    )
    bound = {name: parameters.get(name) for name in statement.parameters}
    started = time.perf_counter()
    try:
        cursor = connection.execute(text(statement.sql), bound)
    except (DBAPIError, SQLAlchemyError) as exc:
        outcome.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        outcome.error = _readable(exc)
        return outcome

    if cursor.returns_rows:
        # Fetch one more than the cap so "there are more" is a fact rather than
        # a guess from a full page.
        fetched = cursor.fetchmany(limit + 1)
        outcome.truncated = len(fetched) > limit
        rows = fetched[:limit]
        outcome.columns = [str(name) for name in cursor.keys()]
        outcome.rows = [
            {column: _json_safe(value) for column, value in zip(outcome.columns, row)}
            for row in rows
        ]
        outcome.row_count = len(rows)
    elif cursor.rowcount is not None and cursor.rowcount >= 0:
        outcome.rows_affected = int(cursor.rowcount)

    outcome.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return outcome


def _require_parameters(script: Script, supplied: dict[str, Any]) -> None:
    missing = [name for name in script.parameters if name not in supplied]
    if missing:
        raise BadRequestError(
            f"This script needs value(s) for: {', '.join(missing)}."
        )


def _readable(exc: Exception) -> str:
    """The database's complaint, without the SQLAlchemy wrapper around it."""
    original = getattr(exc, "orig", None)
    message = str(original if original is not None else exc)
    # SQLAlchemy appends the statement and a docs link; the editor already shows
    # the statement, and the link is noise in an error toast.
    for marker in ("\n[SQL:", "\n(Background on this error"):
        head, sep, _ = message.partition(marker)
        if sep:
            message = head
    return message.strip() or "The database rejected this statement."


def _json_safe(value: Any) -> Any:
    """Render one cell as something JSON can carry."""
    import datetime
    import decimal
    import uuid as uuid_module

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, decimal.Decimal):
        # As text: a decimal that becomes a float on the way to the browser has
        # already lost the exactness it was stored for.
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, uuid_module.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


# ------------------------------------------------------------------- EXPLAIN

#: How each dialect asks for a plan. Absent means the workbench says so rather
#: than guessing a syntax and showing the resulting error as if it were a plan.
_EXPLAIN = {
    "postgresql": "EXPLAIN (FORMAT JSON) {sql}",
    "postgres": "EXPLAIN (FORMAT JSON) {sql}",
    "mysql": "EXPLAIN FORMAT=JSON {sql}",
    "sqlite": "EXPLAIN QUERY PLAN {sql}",
    "duckdb": "EXPLAIN {sql}",
}


@dataclass
class Plan:
    dialect: str
    #: The plan as the database returned it, rendered for display.
    text: str
    #: Parsed rows for dialects that give a table (SQLite).
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Total cost, where the dialect reports one.
    estimated_cost: float | None = None
    estimated_rows: int | None = None
    #: Things worth saying about the plan without pretending to be an optimiser.
    notes: list[str] = field(default_factory=list)


def explain(engine: Engine, sql: str, parameters: dict[str, Any] | None = None) -> Plan:
    """Ask the database how it would run this statement.

    Never `EXPLAIN ANALYZE`: that executes the statement, which is exactly what
    somebody asking for a plan is trying to avoid.
    """
    script = parse(sql)
    if len(script.statements) != 1:
        raise BadRequestError("Select a single statement to explain it.")
    statement = script.statements[0]
    if statement.kind is StatementKind.UNKNOWN:
        raise BadRequestError("This does not look like a statement that can be explained.")

    dialect = engine.dialect.name.lower()
    template = _EXPLAIN.get(dialect)
    if template is None:
        raise BadRequestError(
            f"Query plans are not available for {dialect}: this platform has no "
            "EXPLAIN syntax it can trust for it."
        )

    bound = {name: (parameters or {}).get(name) for name in statement.parameters}
    with engine.connect() as connection:
        try:
            cursor = connection.execute(text(template.format(sql=statement.sql)), bound)
            rows = [dict(row) for row in cursor.mappings()]
        except (DBAPIError, SQLAlchemyError) as exc:
            raise BadRequestError(f"The database could not plan this: {_readable(exc)}") from exc

    return _read_plan(dialect, rows)


def _read_plan(dialect: str, rows: list[dict[str, Any]]) -> Plan:
    import json

    plan = Plan(dialect=dialect, text="", rows=[{k: _json_safe(v) for k, v in r.items()} for r in rows])
    if not rows:
        plan.text = "The database returned no plan."
        return plan

    if dialect in ("postgresql", "postgres"):
        raw = next(iter(rows[0].values()))
        document = json.loads(raw) if isinstance(raw, str) else raw
        plan.text = json.dumps(document, indent=2, default=str)
        root = document[0].get("Plan", {}) if isinstance(document, list) and document else {}
        plan.estimated_cost = _as_float(root.get("Total Cost"))
        plan.estimated_rows = _as_int(root.get("Plan Rows"))
        plan.notes = _plan_notes(root)
        return plan

    if dialect == "mysql":
        raw = next(iter(rows[0].values()))
        document = json.loads(raw) if isinstance(raw, str) else raw
        plan.text = json.dumps(document, indent=2, default=str)
        cost = (document or {}).get("query_block", {}).get("cost_info", {}).get("query_cost")
        plan.estimated_cost = _as_float(cost)
        return plan

    # SQLite and DuckDB return a readable table; show it as one.
    plan.text = "\n".join(
        " | ".join(str(value) for value in row.values()) for row in plan.rows
    )
    if dialect == "sqlite":
        detail = " ".join(str(row.get("detail", "")) for row in plan.rows).upper()
        if "SCAN" in detail and "USING INDEX" not in detail:
            plan.notes.append(
                "This reads the whole table. An index on the filtered column "
                "would usually change that."
            )
    return plan


def _plan_notes(node: dict[str, Any], depth: int = 0) -> list[str]:
    """A few honest observations. Deliberately not an optimiser."""
    notes: list[str] = []
    node_type = str(node.get("Node Type", ""))
    if node_type == "Seq Scan" and _as_float(node.get("Total Cost")) or 0:
        relation = node.get("Relation Name", "a table")
        notes.append(
            f"Sequential scan on {relation}: every row is read. An index on the "
            "filtered column would usually change that."
        )
    if node_type == "Nested Loop" and (_as_int(node.get("Plan Rows")) or 0) > 100_000:
        notes.append(
            "A nested loop over a large estimate is often a missing join index."
        )
    if depth < 6:
        for child in node.get("Plans", []) or []:
            notes.extend(_plan_notes(child, depth + 1))
    # Repeated observations about different tables are useful; identical ones
    # are not.
    return list(dict.fromkeys(notes))


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
