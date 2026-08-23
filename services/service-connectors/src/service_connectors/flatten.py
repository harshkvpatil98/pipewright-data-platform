"""Turning nested documents into rows.

JSON and BSON are trees; a table is not. Every connector that reads a document
store or an API needs the same translation, and doing it twice guarantees that
`user.address.city` means one thing in one place and something else in another.

The rules, and why:

* **Nested objects become dotted columns.** `{"user": {"city": "Rome"}}` becomes
  a column `user.city`. Predictable, and it round-trips back to the path.
* **Arrays become JSON strings, not columns.** Exploding an array either
  multiplies rows -- silently changing what a row means -- or produces
  `tags.0`, `tags.1`, `tags.2` columns whose count depends on the sample. Both
  are worse than a value you can still read.
* **Depth is capped.** A deeply recursive document would otherwise produce
  thousands of columns from one record.
"""

from __future__ import annotations

import json
from typing import Any

MAX_DEPTH = 6
SEPARATOR = "."


def flatten_document(
    document: Any, *, prefix: str = "", depth: int = 0, separator: str = SEPARATOR
) -> dict[str, Any]:
    """One nested document, as a flat mapping of column name to value."""
    if not isinstance(document, dict):
        return {prefix or "value": _scalar(document)}

    flat: dict[str, Any] = {}
    for key, value in document.items():
        name = f"{prefix}{separator}{key}" if prefix else str(key)

        if isinstance(value, dict) and depth < MAX_DEPTH:
            nested = flatten_document(
                value, prefix=name, depth=depth + 1, separator=separator
            )
            # An empty object would otherwise vanish, taking the column with it.
            flat.update(nested or {name: None})
        else:
            flat[name] = _scalar(value)
    return flat


def _scalar(value: Any) -> Any:
    """A value a dataframe cell can hold."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), default=str)
    if isinstance(value, dict):
        # Only reached past the depth cap; keeping it readable beats dropping it.
        return json.dumps(value, default=str)
    return str(value)


def flatten_records(records: list[Any], *, separator: str = SEPARATOR) -> list[dict[str, Any]]:
    """A list of documents, flattened into rows.

    Records with different shapes are fine: the frame built from these gets the
    union of the columns, and the gaps become nulls, which is what a document
    store means by an absent field anyway.
    """
    return [flatten_document(record, separator=separator) for record in records]


def column_union(rows: list[dict[str, Any]]) -> list[str]:
    """Every column across a set of rows, in the order first seen.

    First-seen order rather than alphabetical: the first record's shape is
    usually the one whose field order somebody chose deliberately.
    """
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)
