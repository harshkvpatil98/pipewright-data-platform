"""Autocomplete, from the live schema and from where the cursor is.

The useful part of completion is not the list -- it is the *narrowing*. Offering
every table and every column of every table on every keystroke is a list nobody
reads. So this module works out what position the cursor is in and answers
accordingly:

* after `FROM` or `JOIN`, tables;
* after `alias.`, that table's columns and nothing else;
* after `SELECT`, `WHERE`, `ON`, `GROUP BY` and friends, the columns of the
  tables already named in the statement;
* at the start of a statement, the keywords that can begin one.

Working out which tables are in scope means reading the `FROM` clause, which is
why this module parses a little SQL. It is deliberately shallow -- enough to
find table references and aliases, and no more. A full parser per dialect would
be a large thing to maintain for a feature that is allowed to be approximate:
the cost of being wrong is a suggestion somebody ignores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from service_workbench.schema_tree import SchemaSnapshot, TableInfo


class Context(str, Enum):
    START = "start"
    TABLE = "table"
    COLUMN = "column"
    QUALIFIED_COLUMN = "qualified_column"
    KEYWORD = "keyword"


@dataclass(frozen=True)
class Completion:
    label: str
    kind: str
    detail: str = ""
    #: What to put in the editor, when it differs from the label.
    insert: str = ""
    #: Higher sorts first.
    score: int = 0

    @property
    def text(self) -> str:
        return self.insert or self.label


#: Keywords worth offering. Not the full grammar -- the ones people actually
#: reach for, so the list stays short enough to scan.
KEYWORDS = (
    "SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT",
    "OFFSET", "JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "INNER JOIN",
    "CROSS JOIN", "ON", "AS", "AND", "OR", "NOT", "IN", "EXISTS", "BETWEEN",
    "LIKE", "IS NULL", "IS NOT NULL", "CASE", "WHEN", "THEN", "ELSE", "END",
    "DISTINCT", "UNION", "UNION ALL", "INTERSECT", "EXCEPT", "WITH", "COUNT",
    "SUM", "AVG", "MIN", "MAX", "COALESCE", "CAST", "ASC", "DESC",
)

_STATEMENT_STARTERS = ("SELECT", "WITH", "INSERT INTO", "UPDATE", "DELETE FROM", "EXPLAIN", "SHOW")

#: `FROM x`, `JOIN x y`, `UPDATE x`, `INTO x` -- with an optional alias.
_TABLE_REFERENCE = re.compile(
    r"\b(?:from|join|update|into)\s+"
    r"([a-zA-Z_][\w$]*(?:\.[a-zA-Z_][\w$]*)?|\"[^\"]+\"|`[^`]+`)"
    r"(?:\s+(?:as\s+)?([a-zA-Z_][\w$]*))?",
    re.IGNORECASE,
)

_AFTER_TABLE_KEYWORD = re.compile(r"\b(?:from|join|update|into|table)\s+[\w.\"`]*$", re.IGNORECASE)
_AFTER_COLUMN_KEYWORD = re.compile(
    # Two shapes, because `\b` cannot precede a comma: a keyword followed by
    # whitespace, or punctuation that may be followed by none at all --
    # `SELECT a,b` is as common as `SELECT a, b`.
    r"(?:\b(?:select|where|and|or|on|by|having|set|when|then|else|using)\s+|[,(]\s*)"
    r"[\w.\"`]*$",
    re.IGNORECASE,
)
_QUALIFIER = re.compile(r"([a-zA-Z_][\w$]*)\.([\w$]*)$")
_WORD_AT_END = re.compile(r"([\w$]*)$")

_RESERVED_AFTER_KEYWORD = frozenset(
    {"select", "where", "group", "order", "having", "limit", "on", "using", "set", "values", "as"}
)


@dataclass(frozen=True)
class Cursor:
    """What the caller is asking to complete."""

    context: Context
    #: The partial word being typed, lower-cased.
    prefix: str
    #: For `alias.`, the alias or table name before the dot.
    qualifier: str | None = None


def read_cursor(sql: str, offset: int | None = None) -> Cursor:
    """Work out what kind of thing belongs where the cursor is."""
    head = sql if offset is None else sql[: max(0, offset)]
    # Only the current statement matters; an earlier one's FROM clause is not
    # in scope, and its keywords should not decide this one's context.
    head = head[_last_statement_start(head):]
    stripped = _strip_for_context(head)

    qualified = _QUALIFIER.search(stripped)
    if qualified is not None:
        return Cursor(
            context=Context.QUALIFIED_COLUMN,
            prefix=qualified.group(2).lower(),
            qualifier=qualified.group(1),
        )

    prefix = (_WORD_AT_END.search(stripped).group(1) if stripped else "").lower()
    before = stripped[: len(stripped) - len(prefix)]

    if not before.strip():
        return Cursor(context=Context.START, prefix=prefix)
    if _AFTER_TABLE_KEYWORD.search(stripped):
        return Cursor(context=Context.TABLE, prefix=prefix)
    if _AFTER_COLUMN_KEYWORD.search(stripped):
        return Cursor(context=Context.COLUMN, prefix=prefix)
    return Cursor(context=Context.KEYWORD, prefix=prefix)


def tables_in_scope(sql: str, offset: int | None = None) -> dict[str, str]:
    """Alias (or bare name) -> table name, for the statement under the cursor.

    Reads the *whole* statement, not just the text before the cursor: people
    write `SELECT <cursor> FROM orders` by going back to the column list, and
    that is precisely when completion earns its keep. Scanning only backwards
    would offer nothing at the one moment it is most wanted.

    Both directions are recorded, so `orders.id` resolves whether the writer
    used an alias or repeated the table name.
    """
    statement = sql[_statement_span(sql, offset)]
    found: dict[str, str] = {}
    for match in _TABLE_REFERENCE.finditer(_strip_for_context(statement)):
        table = match.group(1).strip('"').strip("`")
        alias = match.group(2)
        found[table.split(".")[-1].lower()] = table
        found[table.lower()] = table
        if alias and alias.lower() not in _RESERVED_AFTER_KEYWORD:
            found[alias.lower()] = table
    return found


def complete(
    schema: SchemaSnapshot, sql: str, offset: int | None = None, *, limit: int = 50
) -> list[Completion]:
    """Suggestions for the cursor position, best first."""
    cursor = read_cursor(sql, offset)
    scope = tables_in_scope(sql, offset)
    suggestions: list[Completion] = []

    if cursor.context is Context.START:
        suggestions = [
            Completion(label=word, kind="keyword", score=90) for word in _STATEMENT_STARTERS
        ]
    elif cursor.context is Context.TABLE:
        suggestions = [_table_completion(table, schema) for table in schema.tables]
    elif cursor.context is Context.QUALIFIED_COLUMN:
        table_name = scope.get((cursor.qualifier or "").lower(), cursor.qualifier or "")
        table = schema.find(table_name)
        if table is not None and table.loaded:
            suggestions = [_column_completion(column, table, 100) for column in table.columns]
        elif table is not None:
            # The table is real but its columns have not been reflected. Say
            # nothing rather than offering the wrong thing.
            suggestions = []
        else:
            suggestions = [_table_completion(entry, schema) for entry in schema.tables]
    elif cursor.context is Context.COLUMN:
        seen: set[str] = set()
        for name in dict.fromkeys(scope.values()):
            table = schema.find(name)
            if table is None or not table.loaded:
                continue
            for column in table.columns:
                if column.name.lower() in seen:
                    # The same name in two joined tables is ambiguous; offer it
                    # once, qualified, so what gets typed actually compiles.
                    continue
                seen.add(column.name.lower())
                suggestions.append(_column_completion(column, table, 100))
        suggestions += [Completion(label=word, kind="keyword", score=20) for word in KEYWORDS]
    else:
        suggestions = [Completion(label=word, kind="keyword", score=50) for word in KEYWORDS]

    return _rank(suggestions, cursor.prefix)[:limit]


def _table_completion(table: TableInfo, schema: SchemaSnapshot) -> Completion:
    # Qualify only when it is needed: `public.orders` everywhere is noise on a
    # database where everything lives in `public`.
    needs_schema = table.schema is not None and table.schema != schema.default_schema
    label = table.qualified if needs_schema else table.name
    return Completion(
        label=label,
        kind=table.kind,
        detail=f"{table.kind} · {len(table.columns)} columns" if table.loaded else table.kind,
        score=80 if table.kind == "table" else 70,
    )


def _column_completion(column, table: TableInfo, score: int) -> Completion:
    detail = f"{table.name} · {column.type}"
    if column.primary_key:
        detail += " · key"
    elif not column.nullable:
        detail += " · required"
    return Completion(label=column.name, kind="column", detail=detail, score=score)


def _rank(suggestions: list[Completion], prefix: str) -> list[Completion]:
    if not prefix:
        return sorted(suggestions, key=lambda entry: (-entry.score, entry.label.lower()))

    scored: list[tuple[int, Completion]] = []
    for entry in suggestions:
        label = entry.label.lower()
        if label == prefix:
            bonus = 300
        elif label.startswith(prefix):
            bonus = 200
        elif prefix in label:
            bonus = 100
        elif _subsequence(prefix, label):
            # "cn" finds "customer_name", which is the whole reason people type
            # three letters instead of twelve.
            bonus = 40
        else:
            continue
        scored.append((bonus + entry.score, entry))

    scored.sort(key=lambda pair: (-pair[0], pair[1].label.lower()))
    return [entry for _, entry in scored]


def _subsequence(needle: str, haystack: str) -> bool:
    cursor = 0
    for character in needle:
        cursor = haystack.find(character, cursor) + 1
        if cursor == 0:
            return False
    return True


def _strip_for_context(sql: str) -> str:
    """Blank out comments and literals, preserving length so offsets survive."""
    out = list(sql)
    index = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = length if end == -1 else end
            for position in range(index, end):
                out[position] = " "
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for position in range(index, end):
                out[position] = " "
            index = end
            continue
        if character == "'":
            end = index + 1
            while end < length and sql[end] != "'":
                end += 1
            for position in range(index, min(end + 1, length)):
                out[position] = " "
            index = end + 1
            continue
        index += 1
    return "".join(out)


def _last_statement_start(sql: str) -> int:
    """Where the statement under the cursor begins."""
    blanked = _strip_for_context(sql)
    return blanked.rfind(";") + 1


def _statement_span(sql: str, offset: int | None) -> slice:
    """The whole statement the cursor sits in, semicolon to semicolon."""
    position = len(sql) if offset is None else max(0, min(offset, len(sql)))
    blanked = _strip_for_context(sql)
    start = blanked.rfind(";", 0, position) + 1
    end = blanked.find(";", position)
    return slice(start, len(sql) if end == -1 else end)
