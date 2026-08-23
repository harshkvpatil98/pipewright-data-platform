"""Turn a change set into SQL statements.

Everything here is parameterised. Values never reach the SQL text, so a value
containing a quote is data rather than syntax -- which matters more here than
anywhere else in the platform, because this is the one place that writes.

Two ordering rules that are not stylistic:

* **DDL before DML.** Adding a column before writing values into it is not
  optional, and dropping one after the last write to it avoids a needless error.
* **Deletes last.** An update against a row deleted earlier in the same change
  set would silently affect nothing, and the dry run would report a count the
  user then cannot explain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from shared_python.errors import BadRequestError

from service_writeback.edits import DDL_KINDS, Edit, EditKind, validate_all
from service_writeback.identity import TableShape


class Unsupported(BadRequestError):
    """This dialect cannot express this change. Never approximate; refuse."""


@dataclass(frozen=True)
class Statement:
    """One statement, with its parameters kept apart from its text.

    ``param_sets`` carries a statement that runs once per parameter set in a
    single round trip. Rows that update the same columns produce identical SQL,
    so 500 edited rows become one statement instead of 500 -- while the WHERE
    clause stays per-row, which is what keeps the concurrency check exact.
    """

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    param_sets: list[dict[str, Any]] | None = None
    kind: str = "dml"
    #: What this statement is for, shown on the review screen.
    describes: str = ""
    #: How many rows it should affect. None when it cannot be known in advance.
    expected_rows: int | None = None
    irreversible: bool = False

    @property
    def is_ddl(self) -> bool:
        return self.kind == "ddl"


#: Dialects that cannot roll back DDL. A partial failure there is not
#: recoverable, and the person pressing the button deserves to know first.
#:
#: SQLite is in this list for a driver reason rather than an engine one: the
#: database itself has transactional DDL, but pysqlite only opens an implicit
#: transaction for DML, so an ALTER TABLE commits itself and survives the
#: rollback. Verified, not assumed -- a rehearsal that leaves the column behind
#: is not a rehearsal.
NON_TRANSACTIONAL_DDL = frozenset({"mysql", "mariadb", "oracle", "sqlite"})


@dataclass(frozen=True)
class CompiledChange:
    statements: list[Statement]
    #: True when this dialect cannot roll DDL back.
    ddl_is_not_transactional: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def row_estimate(self) -> int:
        return sum(s.expected_rows or 0 for s in self.statements)

    @property
    def has_irreversible(self) -> bool:
        return any(s.irreversible for s in self.statements)


def _quote(engine: Engine, identifier: str) -> str:
    return engine.dialect.identifier_preparer.quote(identifier)


def _qualified(engine: Engine, shape: TableShape) -> str:
    if shape.schema:
        return f"{_quote(engine, shape.schema)}.{_quote(engine, shape.table)}"
    return _quote(engine, shape.table)


def compile_change_set(
    engine: Engine, shape: TableShape, edits: list[Edit]
) -> CompiledChange:
    """Compile edits into ordered, parameterised statements."""
    key_columns = shape.identity.columns
    if not shape.identity.usable and any(
        edit.kind in (EditKind.SET_CELL, EditKind.DELETE_ROW) for edit in edits
    ):
        raise BadRequestError(shape.identity.reason)

    validate_all(edits, columns=shape.columns, key_columns=key_columns)

    dialect = engine.dialect.name
    statements: list[Statement] = []
    warnings: list[str] = []

    # 1. Structure first: a value cannot be written into a column that does not
    #    exist yet.
    for index, edit in enumerate(e for e in edits if e.kind is EditKind.ADD_COLUMN):
        statements.append(_add_column(engine, shape, edit, index))
    for index, edit in enumerate(e for e in edits if e.kind is EditKind.RENAME_COLUMN):
        statements.append(_rename_column(engine, shape, edit, dialect, index))

    # 2. Inserts, then updates: an update may target a row inserted here.
    for index, edit in enumerate(e for e in edits if e.kind is EditKind.INSERT_ROW):
        statements.append(_insert_row(engine, shape, edit, index))

    updates = [e for e in edits if e.kind is EditKind.SET_CELL]
    statements.extend(_updates(engine, shape, updates))

    # 3. Deletes after updates, so an update is never silently a no-op.
    for index, edit in enumerate(e for e in edits if e.kind is EditKind.DELETE_ROW):
        statements.append(_delete_row(engine, shape, edit, index))

    # 4. Dropping a column last, after anything that still reads it.
    for index, edit in enumerate(e for e in edits if e.kind is EditKind.DROP_COLUMN):
        statements.append(_drop_column(engine, shape, edit, dialect, index))

    if not statements:
        raise BadRequestError(
            "Every edit here writes the value the cell already holds, so there is "
            "nothing to apply."
        )

    non_transactional = dialect in NON_TRANSACTIONAL_DDL and any(
        edit.kind in DDL_KINDS for edit in edits
    )
    if non_transactional:
        warnings.append(
            f"{dialect} cannot roll back structure changes. If a later statement "
            "fails, the columns added or dropped here will stay changed and must "
            "be undone by hand."
        )
    if not shape.identity.durable and any(
        edit.kind in (EditKind.SET_CELL, EditKind.DELETE_ROW) for edit in edits
    ):
        warnings.append(shape.identity.caveat or "This table's row key is not enforced.")

    return CompiledChange(statements, non_transactional, warnings)


def _where(engine: Engine, edit: Edit, key_columns: tuple[str, ...], prefix: str) -> tuple[str, dict[str, Any]]:
    """The clause that addresses exactly one row, plus its parameters."""
    if not key_columns:
        raise BadRequestError("Cannot address a row without a key.")
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for position, name in enumerate(key_columns):
        marker = f"{prefix}_k{position}"
        clauses.append(f"{_quote(engine, name)} = :{marker}")
        params[marker] = edit.key[name]
    return " AND ".join(clauses), params


def _updates(engine: Engine, shape: TableShape, edits: list[Edit]) -> list[Statement]:
    """Updates, grouped by row and then batched by shape.

    Two groupings, for two different reasons:

    * **By row** -- three edits to one row are one `UPDATE`, which is faster and
      gives an honest affected-row count.
    * **By shape** -- rows that set the same columns, and check the same
      columns, produce identical SQL. Those run as one statement with many
      parameter sets, so pasting five hundred rows is one round trip rather than
      five hundred. The `WHERE` clause is still per-row, so the concurrency
      check keeps its precision; only the reported row count is per group, and a
      mismatch there still stops the whole commit.
    """
    if not edits:
        return []

    key_columns = shape.identity.columns
    by_row: dict[tuple, dict[str, Edit]] = {}
    for edit in edits:
        if edit.is_noop:
            # Setting a column to the value it already holds is not a change.
            # Dropping it here also avoids a dialect trap: MySQL reports the
            # number of rows it *changed*, not the number it matched, so such an
            # UPDATE returns zero and would be read as a concurrent edit.
            continue
        signature = tuple(edit.key[name] for name in key_columns)
        # Two edits to the same cell: the last one is what the user sees on
        # screen, so it is what gets written.
        by_row.setdefault(signature, {})[str(edit.column)] = edit

    # Group rows whose statements would be character-for-character identical.
    groups: dict[tuple, list[dict[str, Edit]]] = {}
    for row_edits in by_row.values():
        columns = tuple(sorted(row_edits))
        checked = tuple(name for name in columns if row_edits[name].records_previous)
        groups.setdefault((columns, checked), []).append(row_edits)

    statements: list[Statement] = []
    for index, ((columns, checked), rows) in enumerate(groups.items()):
        prefix = f"u{index}"
        assignments = [
            f"{_quote(engine, column)} = :{prefix}_v{position}"
            for position, column in enumerate(columns)
        ]
        where = " AND ".join(
            f"{_quote(engine, name)} = :{prefix}_k{position}"
            for position, name in enumerate(key_columns)
        )
        if not where:
            raise BadRequestError("Cannot address a row without a key.")

        # Optimistic concurrency, per edited cell: each column must still hold
        # what it held when it was read. Zero rows affected then means somebody
        # else changed it, which the commit reports rather than overwriting.
        #
        # Columns the edit did not record are not checked, and an edit that
        # recorded nothing gets no check at all -- stated rather than implied,
        # because a check that is sometimes absent is worse than one that is
        # never there.
        #
        # A concurrent change to a *different* column of the same row is
        # deliberately not a conflict: that is last-write-wins per cell, which is
        # what a grid behaves like and what people expect from one.
        #
        # Comparing values rather than hashing in SQL is deliberate too. A hash
        # function matching Python's is not portable across dialects, and getting
        # it subtly wrong would disable concurrency checking without failing
        # anything.
        #
        # NULL-safe, because `x = NULL` is never true and a previously-null cell
        # would otherwise never match.
        guards = [
            f"({_quote(engine, name)} = :{prefix}_p{position} "
            f"OR ({_quote(engine, name)} IS NULL AND :{prefix}_p{position} IS NULL))"
            for position, name in enumerate(checked)
        ]
        clause = (" AND " + " AND ".join(guards)) if guards else ""

        param_sets: list[dict[str, Any]] = []
        for row_edits in rows:
            row_params: dict[str, Any] = {}
            for position, column in enumerate(columns):
                row_params[f"{prefix}_v{position}"] = row_edits[column].value
            first = next(iter(row_edits.values()))
            for position, name in enumerate(key_columns):
                row_params[f"{prefix}_k{position}"] = first.key[name]
            for position, name in enumerate(checked):
                row_params[f"{prefix}_p{position}"] = row_edits[name].previous
            param_sets.append(row_params)

        rows_word = "row" if len(rows) == 1 else "rows"
        statements.append(
            Statement(
                sql=(
                    f"UPDATE {_qualified(engine, shape)} SET {', '.join(assignments)} "
                    f"WHERE {where}{clause}"
                ),
                params=param_sets[0] if len(param_sets) == 1 else {},
                param_sets=None if len(param_sets) == 1 else param_sets,
                describes=f"update {', '.join(columns)} in {len(rows)} {rows_word}",
                expected_rows=len(rows),
            )
        )
    return statements


def _insert_row(engine: Engine, shape: TableShape, edit: Edit, index: int) -> Statement:
    columns = list(edit.values)
    markers = {f"i{index}_{position}": edit.values[name] for position, name in enumerate(columns)}
    placeholders = ", ".join(f":{name}" for name in markers)
    return Statement(
        sql=(
            f"INSERT INTO {_qualified(engine, shape)} "
            f"({', '.join(_quote(engine, name) for name in columns)}) VALUES ({placeholders})"
        ),
        params=markers,
        describes=f"insert 1 row with {len(columns)} value(s)",
        expected_rows=1,
    )


def _delete_row(engine: Engine, shape: TableShape, edit: Edit, index: int) -> Statement:
    prefix = f"d{index}"
    where, params = _where(engine, edit, shape.identity.columns, prefix)
    return Statement(
        sql=f"DELETE FROM {_qualified(engine, shape)} WHERE {where}",
        params=params,
        describes="delete 1 row",
        expected_rows=1,
        irreversible=True,
    )


def _add_column(engine: Engine, shape: TableShape, edit: Edit, index: int) -> Statement:
    # The type is an identifier-ish fragment, not a value, so it cannot be a
    # bound parameter. It is checked against an allowlist instead.
    column_type = _safe_type(str(edit.column_type))
    return Statement(
        sql=(
            f"ALTER TABLE {_qualified(engine, shape)} "
            f"ADD COLUMN {_quote(engine, str(edit.column))} {column_type}"
        ),
        kind="ddl",
        describes=f"add column {edit.column} ({column_type})",
        expected_rows=0,
    )


def _drop_column(engine: Engine, shape: TableShape, edit: Edit, dialect: str, index: int) -> Statement:
    return Statement(
        sql=(
            f"ALTER TABLE {_qualified(engine, shape)} "
            f"DROP COLUMN {_quote(engine, str(edit.column))}"
        ),
        kind="ddl",
        describes=f"drop column {edit.column}",
        expected_rows=0,
        irreversible=True,
    )


def _rename_column(engine: Engine, shape: TableShape, edit: Edit, dialect: str, index: int) -> Statement:
    if dialect in ("mysql", "mariadb"):
        # Older MySQL needs CHANGE with a full column definition, which needs
        # the existing type; refusing is better than emitting a rename that
        # silently retypes the column.
        raise Unsupported(
            "Renaming a column on MySQL requires restating its full definition, "
            "which this does not do. Rename it in the database directly."
        )
    return Statement(
        sql=(
            f"ALTER TABLE {_qualified(engine, shape)} "
            f"RENAME COLUMN {_quote(engine, str(edit.column))} TO "
            f"{_quote(engine, str(edit.new_name))}"
        ),
        kind="ddl",
        describes=f"rename {edit.column} to {edit.new_name}",
        expected_rows=0,
    )


#: Types a new column may be given. An allowlist rather than an escape, because
#: this fragment is interpolated into DDL and cannot be a bound parameter.
_ALLOWED_TYPES = {
    "text", "varchar", "char", "integer", "int", "bigint", "smallint",
    "numeric", "decimal", "real", "double precision", "float", "boolean",
    "date", "time", "timestamp", "timestamptz", "uuid", "json", "jsonb",
}


def _safe_type(declared: str) -> str:
    """Validate a column type against an allowlist, keeping any length or precision."""
    cleaned = " ".join(declared.strip().lower().split())
    base = cleaned.split("(")[0].strip()
    if base not in _ALLOWED_TYPES:
        raise BadRequestError(
            f"{declared!r} is not a column type this can create. "
            f"Allowed: {', '.join(sorted(_ALLOWED_TYPES))}."
        )
    if "(" in cleaned:
        inside = cleaned.split("(", 1)[1].rstrip(")")
        if not all(part.strip().isdigit() for part in inside.split(",") if part.strip()):
            raise BadRequestError(
                f"{declared!r} has a size that is not a number, so it cannot be used."
            )
    return cleaned.upper()
