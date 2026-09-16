"""A `.sql` dump, read as a document.

This is the one format where inference is unnecessary, because the file states
its own schema: `CREATE TABLE` declares every column's type, nullability and
key. A dump is therefore a *better* source than a CSV of the same data — the
types are the database's own, not a guess from a sample.

**Nothing here is executed, ever.** A dump arrives from outside; `DROP DATABASE`
is a statement like any other, and a dump that is 90% `INSERT` and 10%
something else is exactly how that ends badly. The file is parsed with a
tokeniser that understands SQL string literals and comments, and the only
statements it acts on are `CREATE TABLE` (for the schema) and `INSERT`
(for the rows). Everything else is counted and ignored.

The parser is deliberately small. It handles the shapes `mysqldump`,
`pg_dump` and `sqlite3 .dump` actually emit; anything more exotic is reported
as unparsed rather than half-understood.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import PWType
from shared_python.types import lattice as pw

from service_ingestion.readers.base import ReadResult, declared_profile, normalise_columns
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: SQL types, mapped onto the Phase 08 lattice. The dump's own word for the
#: type is kept in the finding, so `mediumint` is not silently "an integer".
SQL_TYPES: tuple[tuple[str, Any], ...] = (
    (r"^(tiny|small)int", pw.INT16),
    (r"^(medium)?int(eger)?\b", pw.INT32),
    (r"^bigint", pw.INT64),
    (r"^(numeric|decimal|money)", None),  # precision read from the declaration
    (r"^(double|float|real)", pw.FLOAT64),
    (r"^bool", pw.BOOLEAN),
    (r"^(timestamp|datetime)", None),
    (r"^date$", pw.DATE),
    (r"^time($|\()", None),
    (r"^(uuid|uniqueidentifier)", pw.UUID),
    (r"^(json|jsonb)", pw.JSON),
    (r"^(bytea|blob|binary|varbinary)", pw.BYTES),
    (r"^(char|varchar|text|nvarchar|nchar|clob|character)", None),
)

_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_CREATE = re.compile(
    r"CREATE\s+(?:TEMPORARY\s+|TEMP\s+|UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[`\"\[\]\w.]+)\s*\((?P<body>.*)\)\s*[^)]*$",
    re.IGNORECASE | re.DOTALL,
)
_INSERT = re.compile(
    r"INSERT\s+(?:OR\s+\w+\s+|IGNORE\s+|LOW_PRIORITY\s+|DELAYED\s+)?INTO\s+"
    r"(?P<name>[`\"\[\]\w.]+)\s*(?:\((?P<columns>[^)]*)\))?\s*VALUES\s*(?P<values>.+)$",
    re.IGNORECASE | re.DOTALL,
)
#: Constraint lines inside a CREATE TABLE that are not columns.
_CONSTRAINT = re.compile(
    r"^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|KEY|INDEX|CONSTRAINT|CHECK|EXCLUDE)\b",
    re.IGNORECASE,
)
_PRIMARY_KEY_LINE = re.compile(r"PRIMARY\s+KEY\s*\((?P<columns>[^)]*)\)", re.IGNORECASE)


@dataclass
class Column:
    name: str
    sql_type: str
    pw_type: PWType
    nullable: bool = True
    primary_key: bool = False


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    #: Column order used by the INSERT statements, when it differs.
    insert_columns: list[str] | None = None


def split_statements(text: str) -> list[str]:
    """Statements, with literals and comments understood.

    A semicolon inside `'it''s; fine'` does not end a statement, and neither
    does one inside `-- a comment;`. Getting this wrong truncates a dump at the
    first apostrophe in an address.
    """
    statements: list[str] = []
    current: list[str] = []
    index = 0
    length = len(text)
    quote: str | None = None
    while index < length:
        character = text[index]

        if quote:
            current.append(character)
            if character == "\\" and index + 1 < length:
                current.append(text[index + 1])
                index += 2
                continue
            if character == quote:
                # A doubled quote is a literal quote, not the end of the string.
                if index + 1 < length and text[index + 1] == quote:
                    current.append(text[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in ("'", '"', "`"):
            quote = character
            current.append(character)
            index += 1
            continue

        if text.startswith("--", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index)
            index = length if end == -1 else end + 2
            continue

        if character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(character)
        index += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _clean_identifier(raw: str) -> str:
    return raw.strip().strip('`"[]').split(".")[-1]


def _map_type(declaration: str) -> tuple[PWType, str]:
    """A SQL type declaration as a lattice type, keeping the original words."""
    text = declaration.strip()
    lowered = text.lower()
    for pattern, mapped in SQL_TYPES:
        if not re.match(pattern, lowered):
            continue
        if mapped is not None:
            return mapped, text
        if lowered.startswith(("numeric", "decimal", "money")):
            numbers = re.findall(r"\d+", lowered)
            if len(numbers) >= 2:
                return pw.decimal(int(numbers[0]), int(numbers[1])), text
            return pw.decimal(38, 9), text
        if lowered.startswith(("timestamp", "datetime")):
            return pw.timestamp(tz_aware="with time zone" in lowered or "tz" in lowered), text
        if lowered.startswith("time"):
            return pw.time(), text
        numbers = re.findall(r"\d+", lowered)
        return pw.string(int(numbers[0]) if numbers else None), text
    return pw.STRING, text


def _split_definitions(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas that are not inside parentheses.

    `decimal(12,2)` contains a comma that does not separate columns, which is
    why this cannot be `body.split(",")`.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    quote: str | None = None
    for character in body:
        if quote:
            current.append(character)
            if character == quote:
                quote = None
            continue
        if character in ("'", '"', "`"):
            quote = character
            current.append(character)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    if current:
        parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def parse_create(statement: str) -> Table | None:
    match = _CREATE.search(statement)
    if not match:
        return None
    table = Table(name=_clean_identifier(match.group("name")))
    keys: set[str] = set()
    for definition in _split_definitions(match.group("body")):
        if _CONSTRAINT.match(definition):
            key_match = _PRIMARY_KEY_LINE.search(definition)
            if key_match:
                keys.update(
                    _clean_identifier(name) for name in key_match.group("columns").split(",")
                )
            continue
        parts = definition.split(None, 1)
        if len(parts) < 2:
            continue
        name = _clean_identifier(parts[0])
        pw_type, sql_type = _map_type(parts[1])
        lowered = definition.lower()
        table.columns.append(
            Column(
                name=name,
                sql_type=sql_type,
                pw_type=pw_type,
                nullable="not null" not in lowered,
                primary_key="primary key" in lowered,
            )
        )
    for column in table.columns:
        if column.name in keys:
            column.primary_key = True
    return table if table.columns else None


def _parse_values(text: str) -> list[list[Any]]:
    """The tuples of an INSERT ... VALUES clause."""
    rows: list[list[Any]] = []
    current: list[Any] = []
    token: list[str] = []
    quote: str | None = None
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if quote:
            if character == "\\" and index + 1 < length:
                token.append(text[index + 1])
                index += 2
                continue
            if character == quote:
                if index + 1 < length and text[index + 1] == quote:
                    token.append(quote)
                    index += 2
                    continue
                quote = None
                index += 1
                continue
            token.append(character)
            index += 1
            continue

        if character in ("'", '"'):
            quote = character
            index += 1
            continue
        if character == "(":
            depth += 1
            if depth == 1:
                current, token = [], []
                index += 1
                continue
        elif character == ")":
            depth -= 1
            if depth == 0:
                current.append(_literal("".join(token)))
                rows.append(current)
                current, token = [], []
                index += 1
                continue
        elif character == "," and depth == 1:
            current.append(_literal("".join(token)))
            token = []
            index += 1
            continue
        if depth >= 1:
            token.append(character)
        index += 1
    return rows


def _literal(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.upper() == "NULL":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def read_sql_dump(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    """Parse a dump, take its declared schema, and read one table's rows."""
    overrides = dict(overrides or {})
    from service_ingestion.sniff import pipeline

    text, encoding_finding = pipeline.text_of(payload)
    statements = split_statements(text)
    if not statements:
        raise BadRequestError("This file contains no SQL statements.")

    tables: dict[str, Table] = {}
    inserts = 0
    other = 0
    for statement in statements:
        created = parse_create(statement)
        if created is not None:
            tables[created.name] = created
            continue
        insert = _INSERT.search(statement)
        if insert is not None:
            inserts += 1
            name = _clean_identifier(insert.group("name"))
            table = tables.setdefault(name, Table(name=name))
            if insert.group("columns"):
                table.insert_columns = [
                    _clean_identifier(part) for part in insert.group("columns").split(",")
                ]
            table.rows.extend(_parse_values(insert.group("values")))
            continue
        other += 1

    with_rows = {name: table for name, table in tables.items() if table.rows or table.columns}
    if not with_rows:
        raise BadRequestError(
            "No CREATE TABLE or INSERT statement was found in this dump."
        )

    requested = overrides.get("table")
    if requested is not None and str(requested) not in with_rows:
        raise BadRequestError(
            f"This dump has no table called '{requested}'. It has: "
            f"{', '.join(sorted(with_rows))}."
        )
    name = str(requested) if requested is not None else max(
        with_rows, key=lambda key: len(with_rows[key].rows)
    )
    table = with_rows[name]

    findings: list[Finding] = [
        encoding_finding,
        certain(
            "sql_dump",
            name,
            (
                f"{len(with_rows)} table(s) in this dump; reading '{name}'. "
                f"{inserts} INSERT statement(s) parsed, {other} other statement(s) ignored. "
                "Nothing in the file was executed."
            ),
            evidence=sorted(with_rows)[:10],
        ),
    ]
    if len(with_rows) > 1 and requested is None:
        findings.append(
            Finding(
                stage="table_choice",
                value=name,
                certainty=Certainty.UNCERTAIN,
                confidence=0.6,
                reason=(
                    f"'{name}' has the most rows, so it was read. Each of the other "
                    f"{len(with_rows) - 1} table(s) can become its own dataset."
                ),
                candidates=[
                    Candidate(other_name, len(other_table.rows) / max(len(table.rows), 1),
                              f"{len(other_table.rows)} rows")
                    for other_name, other_table in sorted(
                        with_rows.items(), key=lambda item: -len(item[1].rows)
                    )[:5]
                ],
                evidence=sorted(with_rows)[:10],
            )
        )

    columns = [column.name for column in table.columns] or table.insert_columns
    if not columns and table.rows:
        columns = [f"column_{index + 1}" for index in range(len(table.rows[0]))]
    if not columns:
        raise BadRequestError(f"Table '{name}' has no columns this parser could read.")

    order = table.insert_columns or columns
    rows = table.rows[:limit] if limit else table.rows
    width = len(order)
    rectangular = [list(row[:width]) + [None] * max(0, width - len(row)) for row in rows]
    frame = normalise_columns(pd.DataFrame(rectangular, columns=order))

    declared = []
    if table.columns:
        by_name = {column.name: column for column in table.columns}
        for column_name in frame.columns:
            column = by_name.get(column_name)
            if column is None:
                continue
            declared.append(
                declared_profile(
                    column.name,
                    column.pw_type,
                    (
                        f"Declared `{column.sql_type}` by the dump's CREATE TABLE"
                        + (", primary key" if column.primary_key else "")
                        + (", NOT NULL" if not column.nullable else "")
                        + ". Taken from the declaration rather than inferred from values."
                    ),
                )
            )

    return ReadResult(
        frame=frame,
        options={"table": name, "encoding": encoding_finding.value},
        findings=findings,
        declared_columns=declared,
        tables=sorted(with_rows),
        warnings=(
            [f"{other} statement(s) other than CREATE TABLE and INSERT were ignored."]
            if other
            else []
        ),
    )
