"""The first lines of a text without splitting all of it (A8).

`text.splitlines()` on a 100MB file makes two million strings to throw away
all but the first few hundred; that was 215MB of a large upload's memory.
These walk the text instead, breaking lines exactly where `splitlines` does.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

#: Every break `str.splitlines` honours.
SPLITLINES_BREAK = re.compile("\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85  ]")


def iter_lines(text: str, start: int = 0) -> Iterator[str]:
    """The lines of `text` from `start`, one at a time, as `splitlines` makes them."""
    position = start
    for match in SPLITLINES_BREAK.finditer(text, start):
        yield text[position:match.start()]
        position = match.end()
    if position < len(text):
        yield text[position:]


def head_lines(text: str, count: int) -> list[str]:
    """`text.splitlines()[:count]`, without splitting the rest."""
    lines: list[str] = []
    if count <= 0:
        return lines
    for line in iter_lines(text):
        lines.append(line)
        if len(lines) >= count:
            break
    return lines


def offset_of_line(text: str, number: int) -> int:
    """Where line `number` (0-based, counted as `splitlines` counts) starts."""
    if number <= 0:
        return 0
    for index, match in enumerate(SPLITLINES_BREAK.finditer(text), start=1):
        if index == number:
            return match.end()
    return len(text)
