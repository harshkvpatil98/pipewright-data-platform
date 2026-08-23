"""Read-only enforcement for user-supplied extraction SQL.

Extraction lets operators write their own SELECT against a customer database.
That is useful and also the most dangerous input the platform accepts, so every
query passes through :func:`ensure_read_only_select` before it reaches a driver.
The checks run against a copy with comments and string literals stripped, so a
keyword hidden inside a literal cannot smuggle a statement past the scan.
"""

from __future__ import annotations

import re

from shared_python.errors import BadRequestError

# Statements that modify data or schema. `WITH x AS (DELETE ... RETURNING *)` is
# a valid data-modifying CTE in PostgreSQL, so these are rejected anywhere in the
# statement rather than only in leading position.
_FORBIDDEN_KEYWORDS = frozenset(
    {
        "alter",
        "attach",
        "call",
        "copy",
        "create",
        "delete",
        "detach",
        "drop",
        "exec",
        "execute",
        "grant",
        "insert",
        "into",
        "merge",
        "pragma",
        "revoke",
        "truncate",
        "update",
        "vacuum",
    }
)

_ALLOWED_LEADING_KEYWORDS = frozenset({"select", "with"})

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTED = re.compile(r"'(?:''|\\'|[^'])*'", re.DOTALL)
_DOUBLE_QUOTED = re.compile(r'"(?:""|\\"|[^"])*"', re.DOTALL)
_BACKTICK_QUOTED = re.compile(r"`(?:``|[^`])*`", re.DOTALL)
_WORD = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*")

MAX_QUERY_LENGTH = 20_000


def strip_sql_noise(sql: str) -> str:
    """Remove comments and quoted literals so keyword scanning sees only code."""
    without_comments = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql))
    without_literals = _SINGLE_QUOTED.sub(" '' ", without_comments)
    without_literals = _DOUBLE_QUOTED.sub(" ident ", without_literals)
    return _BACKTICK_QUOTED.sub(" ident ", without_literals)


def ensure_read_only_select(sql: str) -> str:
    """Validate that `sql` is a single read-only SELECT and return it trimmed.

    Raises BadRequestError with an operator-readable reason on rejection.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise BadRequestError("Extraction query cannot be empty.")

    trimmed = sql.strip()
    if len(trimmed) > MAX_QUERY_LENGTH:
        raise BadRequestError(
            f"Extraction query is too long ({len(trimmed)} characters, limit {MAX_QUERY_LENGTH})."
        )

    scannable = strip_sql_noise(trimmed)

    # A trailing semicolon is conventional; anything after one is a second statement.
    body, _, remainder = scannable.partition(";")
    if remainder.strip():
        raise BadRequestError("Extraction query must be a single statement; remove everything after the semicolon.")

    words = [match.group(0).lower() for match in _WORD.finditer(body)]
    if not words:
        raise BadRequestError("Extraction query cannot be empty.")

    if words[0] not in _ALLOWED_LEADING_KEYWORDS:
        raise BadRequestError(
            f"Extraction query must begin with SELECT or WITH (found '{words[0].upper()}'). "
            "Only read-only queries are allowed."
        )

    forbidden = sorted({word for word in words if word in _FORBIDDEN_KEYWORDS})
    if forbidden:
        raise BadRequestError(
            f"Extraction query contains disallowed keyword(s): {', '.join(kw.upper() for kw in forbidden)}. "
            "Only read-only queries are allowed."
        )

    return trimmed
