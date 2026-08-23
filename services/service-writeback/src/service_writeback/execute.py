"""Run a compiled change set -- for real, or as a rehearsal.

The dry run is not an estimate. It executes the statements inside a transaction
and then rolls it back, so the row counts it reports are the counts the database
actually produced. An estimate would be wrong exactly when it mattered: a WHERE
clause that matches nothing, or matches far too much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text

from shared_python.errors import BadRequestError, ConflictError
from shared_python.logging import get_logger

from service_writeback.compiler import CompiledChange, Statement
from service_writeback.edits import (
    BLAST_SHARE_FLOOR_ROWS,
    DEFAULT_BLAST_RADIUS,
    DEFAULT_BLAST_SHARE,
)
from service_writeback.identity import TableShape

logger = get_logger(__name__)


@dataclass
class StatementOutcome:
    sql: str
    describes: str
    rows_affected: int
    expected_rows: int | None
    is_ddl: bool = False
    irreversible: bool = False

    @property
    def surprised(self) -> bool:
        """True when the database did something other than what was expected.

        Zero rows from a statement that should have hit one is the important
        case: it means the row is gone, or somebody else changed it.
        """
        return self.expected_rows is not None and self.rows_affected != self.expected_rows


@dataclass
class ChangeResult:
    outcomes: list[StatementOutcome] = field(default_factory=list)
    rows_affected: int = 0
    committed: bool = False
    warnings: list[str] = field(default_factory=list)
    #: Statements whose row count did not match, in the order they ran.
    conflicts: list[StatementOutcome] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class BlastRadius:
    """How much of the table a change touches, and whether that needs confirming."""

    rows_affected: int
    table_rows: int
    threshold: int = DEFAULT_BLAST_RADIUS
    share_threshold: float = DEFAULT_BLAST_SHARE
    share_floor: int = BLAST_SHARE_FLOOR_ROWS

    @property
    def share(self) -> float:
        return 0.0 if self.table_rows == 0 else self.rows_affected / self.table_rows

    @property
    def needs_confirmation(self) -> bool:
        if self.rows_affected > self.threshold:
            return True
        return self.rows_affected >= self.share_floor and self.share > self.share_threshold

    def explain(self) -> str:
        if not self.needs_confirmation:
            return f"{self.rows_affected:,} row(s) of {self.table_rows:,}."
        return (
            f"{self.rows_affected:,} row(s) of {self.table_rows:,} "
            f"({self.share:.0%} of the table). Confirm by typing the table name."
        )


def count_rows(engine: Engine, shape: TableShape) -> int:
    quoted = _qualified(engine, shape)
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar_one())


def _qualified(engine: Engine, shape: TableShape) -> str:
    quote = engine.dialect.identifier_preparer.quote
    return f"{quote(shape.schema)}.{quote(shape.table)}" if shape.schema else quote(shape.table)


def dry_run(engine: Engine, compiled: CompiledChange) -> ChangeResult:
    """Execute and roll back, reporting the counts the database produced.

    DDL is skipped on dialects that cannot roll it back: rehearsing a change
    that cannot be undone is not a rehearsal, it is the change.
    """
    result = ChangeResult(warnings=list(compiled.warnings))
    skip_ddl = compiled.ddl_is_not_transactional

    skipped_any_ddl = False
    #: Filled in statement order, so a caller can line outcomes up with the plan.
    outcomes: list[StatementOutcome | None] = [None] * len(compiled.statements)

    connection = engine.connect()
    transaction = connection.begin()
    try:
        for index, statement in enumerate(compiled.statements):
            if statement.is_ddl and skip_ddl:
                skipped_any_ddl = True
                continue
            try:
                outcome = _run_one(connection, statement)
            except Exception as exc:
                if skipped_any_ddl:
                    # This statement needs structure the rehearsal was not
                    # allowed to create. Reporting the driver error would be
                    # reporting an artefact of the rehearsal, not a problem
                    # with the change itself.
                    result.warnings.append(
                        f"{statement.describes} could not be rehearsed: it depends on a "
                        "structure change this database will not let us try first."
                    )
                    break
                raise BadRequestError(f"The change could not be rehearsed: {exc}") from exc
            outcomes[index] = outcome
            if not outcome.is_ddl:
                result.rows_affected += outcome.rows_affected
            if outcome.surprised:
                result.conflicts.append(outcome)
    finally:
        # Always. The whole point of a rehearsal is that nothing survives it.
        transaction.rollback()
        connection.close()

    result.outcomes = [
        outcome
        if outcome is not None
        else StatementOutcome(
            sql=statement.sql,
            describes=statement.describes + " (not rehearsed)",
            rows_affected=0,
            expected_rows=statement.expected_rows,
            is_ddl=statement.is_ddl,
            irreversible=statement.irreversible,
        )
        for statement, outcome in zip(compiled.statements, outcomes)
    ]

    if skipped_any_ddl:
        result.warnings.append(
            "Structure changes were not rehearsed, because this database cannot "
            "roll them back. Their effect is unverified until you commit."
        )
    return result


def commit(
    engine: Engine,
    compiled: CompiledChange,
    *,
    allow_conflicts: bool = False,
) -> ChangeResult:
    """Apply the change set in one transaction.

    A statement that affects a different number of rows than expected aborts the
    whole thing unless the caller has explicitly accepted that. Silently writing
    when the row underneath has changed is the failure this service exists to
    prevent.
    """
    result = ChangeResult(warnings=list(compiled.warnings))
    connection = engine.connect()
    transaction = connection.begin()
    try:
        for statement in compiled.statements:
            outcome = _run_one(connection, statement)
            result.outcomes.append(outcome)
            if not outcome.is_ddl:
                result.rows_affected += outcome.rows_affected
            if outcome.surprised:
                result.conflicts.append(outcome)
                if not allow_conflicts:
                    transaction.rollback()
                    connection.close()
                    raise ConflictError(
                        f"{outcome.describes} affected {outcome.rows_affected} row(s) "
                        f"instead of {outcome.expected_rows}. Somebody else has "
                        "changed this data since it was read; nothing was written."
                    )
        transaction.commit()
        result.committed = True
    except ConflictError:
        raise
    except Exception as exc:
        transaction.rollback()
        logger.warning("writeback_failed", extra={"error": str(exc)})
        raise BadRequestError(f"The change could not be applied: {exc}") from exc
    finally:
        if not connection.closed:
            connection.close()
    return result


def _run_one(connection: Any, statement: Statement) -> StatementOutcome:
    # A statement with many parameter sets runs once, in one round trip. The
    # driver reports the total rows affected, which is what `expected_rows`
    # holds for a batch -- so a stale row still stops the commit, it just names
    # the batch rather than the row.
    bind = statement.param_sets if statement.param_sets is not None else statement.params
    cursor = connection.execute(text(statement.sql), bind)
    # DDL reports -1; treat it as zero rows rather than as a count.
    affected = int(cursor.rowcount) if cursor.rowcount is not None and cursor.rowcount >= 0 else 0
    return StatementOutcome(
        sql=statement.sql,
        describes=statement.describes,
        rows_affected=affected,
        expected_rows=statement.expected_rows,
        is_ddl=statement.is_ddl,
        irreversible=statement.irreversible,
    )


def export_as_migration(compiled: CompiledChange, *, title: str) -> str:
    """Render the change as a reviewable SQL file.

    For teams whose process does not allow a tool to write to production.
    Refusing to support that workflow would just push people back to editing a
    spreadsheet and mailing it around, which is worse in every way.

    Values are inlined here because a migration file has no parameter binding.
    They are literal-escaped, and the file is meant to be read before it is run.
    """
    lines = [
        f"-- {title}",
        "-- Generated by Pipewright. Review before running.",
        "BEGIN;",
        "",
    ]
    for statement in compiled.statements:
        lines.append(f"-- {statement.describes}")
        # A batched statement runs once per parameter set, so the file needs one
        # written-out statement per set. A migration with bind markers left in
        # it is not a migration.
        for params in statement.param_sets or [statement.params]:
            lines.append(_inline(statement.sql, params) + ";")
        lines.append("")
    lines.append("COMMIT;")
    return "\n".join(lines)


def _inline(sql: str, params: dict[str, Any]) -> str:
    """Substitute bound parameters into the SQL for a file that cannot bind them."""
    # Longest names first, so `:u0_k10` is not partly replaced by `:u0_k1`.
    for name in sorted(params, key=len, reverse=True):
        sql = sql.replace(f":{name}", _literal(params[name]))
    return sql


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"
