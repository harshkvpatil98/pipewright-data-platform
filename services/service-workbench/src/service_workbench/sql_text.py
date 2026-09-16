"""Reading a script as a sequence of statements.

The extraction service already refuses anything that is not a single read-only
SELECT, and that is right for extraction. A workbench cannot work that way:
people paste scripts, and a script that silently ran only its first statement
would be worse than one that refused the lot.

So this module does the thing extraction deliberately avoided -- it splits --
and it does it by scanning the original text rather than a stripped copy,
because the statements have to come back out with their formatting, their
comments, and their character offsets intact. An editor that reports "error in
statement 3" needs to be able to point at statement 3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from shared_python.errors import BadRequestError

#: Longer than any query a person writes by hand, short enough that a paste
#: accident is refused before it reaches a driver.
MAX_SCRIPT_LENGTH = 200_000

#: More than this and it is a migration, not a workbench session.
MAX_STATEMENTS = 100


class StatementKind(str, Enum):
    """What a statement does, decided from its leading keyword.

    Coarse on purpose. The question this answers is "may this run in read-only
    mode", and for that "it writes something" is the whole answer -- classifying
    an UPDATE apart from a DELETE would add cases without adding safety.
    """

    #: SELECT, WITH ... SELECT, SHOW, DESCRIBE, EXPLAIN.
    READ = "read"
    #: INSERT, UPDATE, DELETE, MERGE, TRUNCATE, COPY.
    WRITE = "write"
    #: CREATE, ALTER, DROP, and friends.
    DDL = "ddl"
    #: BEGIN, COMMIT, ROLLBACK, SAVEPOINT, SET.
    SESSION = "session"
    #: Nothing recognisable. Refused rather than guessed at.
    UNKNOWN = "unknown"

    @property
    def writes(self) -> bool:
        return self in (StatementKind.WRITE, StatementKind.DDL)


_READ_LEADING = frozenset({"select", "with", "show", "describe", "desc", "explain", "values", "table"})
_WRITE_LEADING = frozenset({"insert", "update", "delete", "merge", "replace", "truncate", "copy", "upsert"})
_DDL_LEADING = frozenset({"create", "alter", "drop", "rename", "comment", "grant", "revoke", "vacuum", "analyze", "reindex", "cluster"})
_SESSION_LEADING = frozenset({"begin", "start", "commit", "rollback", "savepoint", "release", "set", "use", "reset", "discard", "lock", "unlock"})

#: Keywords that turn a read into a write wherever they appear. A
#: data-modifying CTE is the reason: `WITH x AS (DELETE ... RETURNING *) SELECT`
#: leads with WITH and deletes rows.
_WRITE_ANYWHERE = _WRITE_LEADING | (_DDL_LEADING - {"analyze", "explain"})

_WORD = re.compile(r"[a-zA-Z_][a-zA-Z_0-9$]*")

#: `:name`, but not `::type` (a Postgres cast) and not `:=`.
_PARAMETER = re.compile(r"(?<![:\w]):([a-zA-Z_][a-zA-Z_0-9]*)")


@dataclass(frozen=True)
class Statement:
    """One statement, with everything needed to report on it in place."""

    sql: str
    #: 1-based, in the order they appear.
    index: int
    #: Character offsets into the original script, so an editor can highlight.
    start: int
    end: int
    #: 1-based line the statement starts on.
    line: int
    kind: StatementKind
    #: Named parameters this statement references, in first-appearance order.
    parameters: tuple[str, ...] = ()

    #: Longest a results-tab label can be before it stops being a label.
    SUMMARY_LENGTH = 60

    @property
    def summary(self) -> str:
        """A short label for a results tab, never longer than SUMMARY_LENGTH."""
        collapsed = " ".join(self.sql.split())
        if len(collapsed) <= self.SUMMARY_LENGTH:
            return collapsed
        return collapsed[: self.SUMMARY_LENGTH - 1] + "…"


@dataclass
class Script:
    statements: list[Statement] = field(default_factory=list)

    @property
    def parameters(self) -> list[str]:
        """Every parameter the script needs, deduplicated, in order of appearance."""
        seen: list[str] = []
        for statement in self.statements:
            for name in statement.parameters:
                if name not in seen:
                    seen.append(name)
        return seen

    @property
    def writes(self) -> bool:
        return any(statement.kind.writes for statement in self.statements)


def split(script: str) -> list[tuple[str, int, int]]:
    """Cut a script into statements at top-level semicolons.

    Walks the original characters rather than a stripped copy, because the
    offsets are part of the answer. Handles single quotes with doubling, double
    quotes and backticks for identifiers, line and block comments, and
    PostgreSQL dollar-quoted bodies -- which is what makes a function definition
    containing semicolons survive intact.
    """
    pieces: list[tuple[str, int, int]] = []
    start = 0
    index = 0
    length = len(script)

    while index < length:
        character = script[index]

        if character == "'":
            index = _skip_quoted(script, index, "'")
            continue
        if character == '"':
            index = _skip_quoted(script, index, '"')
            continue
        if character == "`":
            index = _skip_quoted(script, index, "`")
            continue
        if script.startswith("--", index):
            newline = script.find("\n", index)
            index = length if newline == -1 else newline + 1
            continue
        if script.startswith("/*", index):
            close = script.find("*/", index + 2)
            index = length if close == -1 else close + 2
            continue
        if character == "$":
            after = _skip_dollar_quoted(script, index)
            if after is not None:
                index = after
                continue

        if character == ";":
            body = script[start:index]
            if body.strip():
                pieces.append((body, start, index))
            start = index + 1
        index += 1

    tail = script[start:length]
    if tail.strip():
        pieces.append((tail, start, length))
    return pieces


def _skip_quoted(script: str, index: int, quote: str) -> int:
    """Return the index just past a quoted run beginning at ``index``."""
    length = len(script)
    cursor = index + 1
    while cursor < length:
        if script[cursor] == "\\" and quote == "'":
            # MySQL honours backslash escapes inside single quotes; PostgreSQL
            # does not by default. Skipping the pair is right for MySQL and
            # harmless for PostgreSQL, where `\` is an ordinary character and
            # the next one cannot be an unescaped closing quote anyway.
            cursor += 2
            continue
        if script[cursor] == quote:
            if cursor + 1 < length and script[cursor + 1] == quote:
                cursor += 2  # a doubled quote is a literal quote
                continue
            return cursor + 1
        cursor += 1
    return length


_DOLLAR_TAG = re.compile(r"\$([a-zA-Z_][a-zA-Z_0-9]*)?\$")


def _skip_dollar_quoted(script: str, index: int) -> int | None:
    """Skip a PostgreSQL ``$tag$ ... $tag$`` body, or return None if not one."""
    match = _DOLLAR_TAG.match(script, index)
    if match is None:
        return None
    tag = match.group(0)
    close = script.find(tag, match.end())
    return len(script) if close == -1 else close + len(tag)


def classify(sql: str) -> StatementKind:
    """What this statement does. Scans a comment- and literal-free copy."""
    from service_extraction.sql_safety import strip_sql_noise

    words = [match.group(0).lower() for match in _WORD.finditer(strip_sql_noise(sql))]
    if not words:
        return StatementKind.UNKNOWN

    leading = words[0]
    if leading in _SESSION_LEADING:
        return StatementKind.SESSION

    # A data-modifying CTE leads with WITH and still writes, so the whole
    # statement is scanned before the leading keyword is trusted.
    if leading in _READ_LEADING:
        if leading == "explain":
            # `EXPLAIN ANALYZE INSERT ...` actually runs the insert.
            body = words[1:]
            if body and body[0] == "analyze" and any(w in _WRITE_ANYWHERE for w in body):
                return StatementKind.WRITE
            return StatementKind.READ
        offending = [word for word in words[1:] if word in _WRITE_ANYWHERE]
        if offending:
            return StatementKind.DDL if offending[0] in _DDL_LEADING else StatementKind.WRITE
        return StatementKind.READ

    if leading in _WRITE_LEADING:
        return StatementKind.WRITE
    if leading in _DDL_LEADING:
        return StatementKind.DDL
    return StatementKind.UNKNOWN


def parameters_in(sql: str) -> tuple[str, ...]:
    """Named `:parameters`, ignoring casts and anything inside a literal."""
    from service_extraction.sql_safety import strip_sql_noise

    seen: list[str] = []
    for match in _PARAMETER.finditer(strip_sql_noise(sql)):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def parse(script: str) -> Script:
    """Read a script into statements, or say what is wrong with it."""
    if not isinstance(script, str) or not script.strip():
        raise BadRequestError("There is no SQL to run.")
    if len(script) > MAX_SCRIPT_LENGTH:
        raise BadRequestError(
            f"That script is {len(script):,} characters; the limit is "
            f"{MAX_SCRIPT_LENGTH:,}."
        )

    pieces = split(script)
    if not pieces:
        raise BadRequestError("There is no SQL to run.")
    if len(pieces) > MAX_STATEMENTS:
        raise BadRequestError(
            f"That script has {len(pieces)} statements; the limit is {MAX_STATEMENTS}. "
            "Run it in parts, or save it as a migration."
        )

    statements: list[Statement] = []
    for position, (body, start, end) in enumerate(pieces, start=1):
        # Report the position of the first real character, not of the
        # whitespace the previous statement's semicolon left behind.
        offset = len(body) - len(body.lstrip())
        statements.append(
            Statement(
                sql=body.strip(),
                index=position,
                start=start + offset,
                end=end,
                line=script.count("\n", 0, start + offset) + 1,
                kind=classify(body),
                parameters=parameters_in(body),
            )
        )
    return Script(statements=statements)
