"""Counting things in messages people read: "1 column", "3 columns", never "column(s)"."""

from __future__ import annotations

from collections.abc import Sequence


def noun(count: int, singular: str, plural: str | None = None) -> str:
    """The noun that goes with a count."""
    return singular if count == 1 else (plural or f"{singular}s")


def count_of(count: int, singular: str, plural: str | None = None) -> str:
    """A count with its noun: "1 project", "12 projects"."""
    return f"{count:,} {noun(count, singular, plural)}"


def listing(items: Sequence[object], *, limit: int = 10) -> str:
    """Names joined for a sentence, cut short past `limit`: "a, b and c"."""
    names = [str(item) for item in items]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"
