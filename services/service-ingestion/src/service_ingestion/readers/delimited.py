"""CSV and its relatives, which is where most of the difficulty lives.

Everything the sniffing stage worked out gets applied here, plus the things
that only show up once you actually read the file: ragged rows, trailing
delimiters, and the footer line that says "Total: 4,812.00" and has two fields
where the table has nine.

Ragged rows are the interesting case. pandas either raises or silently drops
them depending on the setting, and both are wrong: the row exists and somebody
needs to know. They are counted, sampled, and reported, and the read continues.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff import pipeline
from service_ingestion.sniff.delimiter import count_fields
from service_ingestion.sniff.evidence import Certainty, Finding, certain
from service_ingestion.sniff.lines import offset_of_line
from shared_python.words import count_of

#: Ragged rows sampled for the report. Enough to see the pattern; a file where
#: every row is ragged has a different problem than one where row 4,812 is.
MAX_RAGGED_SAMPLE = 10

#: Field size ceiling. The default is 128KB and a single quoted field holding a
#: base64 blob exceeds it, which surfaces as an unhelpful `_csv.Error`.
FIELD_LIMIT = 10 * 1024 * 1024


def read_delimited(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    """A delimited text file, read the way the sniff says it should be."""
    overrides = dict(overrides or {})
    text, encoding_finding = pipeline.text_of(payload)
    dialect, layout = pipeline.structure_of(text, overrides=overrides)

    findings = [encoding_finding, dialect.finding, dialect.quote_finding, layout.finding]

    # The body starts after the preamble. Lines are walked one at a time, never
    # held as a list: two million line strings cost more than the file (A8).
    # Counted as the header sniff counts lines, so `skip_rows` means the same.
    body_start = offset_of_line(text, layout.skip_rows)
    expected = len(layout.columns) if layout.columns else None
    ragged: list[tuple[int, int]] = []
    rows = 0
    for offset, line in enumerate(_lines(text, body_start)):
        if not line.strip():
            continue
        rows += 1
        if expected and offset > 0:
            width = count_fields(line, dialect.delimiter, dialect.quote_char, dialect.escape_char)
            # A trailing delimiter produces one extra empty field on every row;
            # that is a dialect quirk rather than a ragged row.
            if width != expected and not (width == expected + 1 and line.rstrip().endswith(dialect.delimiter)):
                ragged.append((layout.skip_rows + offset + 1, width))
        if limit and rows > limit + 1:
            break
    if not rows:
        raise BadRequestError("There are no rows after the header.")

    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(FIELD_LIMIT)
        # pandas' C parser, given UTF-8 bytes, needs about a quarter of the
        # memory of the Python one given a string (which holds every character
        # in four bytes) and is three times faster: 490MB rather than 1.85GB
        # for a 99MB file. A delimiter it cannot take keeps the Python parser.
        fast = len(dialect.delimiter) == 1 and (dialect.escape_char is None or len(dialect.escape_char) == 1)
        if fast and body_start == 0 and encoding_finding.value in ("utf-8", "ascii"):
            # Already UTF-8 from the first byte: no need for a second copy.
            source: Any = io.BytesIO(payload)
        elif fast:
            source = io.BytesIO(text[body_start:].encode("utf-8"))
        else:
            source = io.StringIO(text[body_start:])
        # The decoded text has done its work (sniffing, counting ragged rows);
        # let it go before the parse, the step that needs the most memory.
        del text
        # The names come from `header.py`, which has already made them distinct
        # and usable. Letting pandas dedupe instead produces `amount.1`, which
        # looks like a real column name and is not the one the file used.
        frame = pd.read_csv(
            source,
            sep=dialect.delimiter,
            quotechar=dialect.quote_char,
            escapechar=dialect.escape_char,
            header=None,
            names=layout.columns or None,
            skiprows=1 if layout.has_header else 0,
            dtype=str,
            keep_default_na=False,
            na_values=[],
            skip_blank_lines=True,
            engine="c" if fast else "python",
            # Bytes that are not UTF-8 read as U+FFFD, as the decoding above did.
            **({"encoding": "utf-8", "encoding_errors": "replace"} if fast else {}),
            # Ragged rows are counted above and reported; dropping them here
            # keeps the frame rectangular without pretending they never existed.
            on_bad_lines="skip",
            nrows=limit,
        )
    except pd.errors.EmptyDataError as exc:
        raise BadRequestError("This file has no data rows.") from exc
    except pd.errors.ParserError as exc:
        raise BadRequestError(f"Could not read this file as delimited text: {exc}") from exc
    finally:
        csv.field_size_limit(previous)

    frame = normalise_columns(frame)

    warnings: list[str] = []
    if ragged:
        sample = ", ".join(f"line {line} has {width}" for line, width in ragged[:MAX_RAGGED_SAMPLE])
        findings.append(
            Finding(
                stage="ragged_rows",
                value=len(ragged),
                certainty=Certainty.CERTAIN,
                confidence=1.0,
                reason=(
                    f"{count_of(len(ragged), 'row')} do not have {expected} fields and were skipped. "
                    "A footer total or a stray delimiter usually explains it."
                ),
                evidence=[sample],
            )
        )
        warnings.append(f"{count_of(len(ragged), 'ragged row')} were skipped.")
    else:
        findings.append(certain("ragged_rows", 0, "Every row has the same number of fields."))

    return ReadResult(
        frame=frame,
        options={
            "delimiter": dialect.delimiter,
            "quote_char": dialect.quote_char,
            "escape_char": dialect.escape_char,
            "encoding": encoding_finding.value,
            "skip_rows": layout.skip_rows,
            "has_header": layout.has_header,
        },
        findings=findings,
        warnings=warnings,
    )


def _lines(text: str, start: int = 0):
    """The lines of `text` from `start`, one at a time, like `splitlines`."""
    position = start
    for match in _LINE_BREAK.finditer(text, start):
        yield text[position:match.start()]
        position = match.end()
    if position < len(text):
        yield text[position:]


#: The breaks pandas' parser also honours: \r\n, \r and \n.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def read_fixed_width(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    """A file whose columns are positions rather than separators.

    Boundaries are found where the character-frequency profile has a valley: a
    column gap is a position that is a space on nearly every line. Given
    boundaries in the spec, those are used instead -- a COBOL copybook is a
    better source than any inference.
    """
    overrides = dict(overrides or {})
    text, encoding_finding = pipeline.text_of(payload)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise BadRequestError("This file has no data rows.")

    supplied = overrides.get("column_widths") or overrides.get("colspecs")
    if supplied:
        colspecs = [tuple(pair) for pair in supplied]
        finding = certain(
            "column_boundaries",
            colspecs,
            "Column positions supplied with the file rather than inferred.",
        )
    else:
        colspecs, finding = _infer_boundaries(lines)

    skip = int(overrides.get("skip_rows") or 0)
    frame = pd.read_fwf(
        io.StringIO("\n".join(lines[skip:])),
        colspecs=colspecs,
        dtype=str,
        header=0 if overrides.get("has_header", True) else None,
        nrows=limit,
    )
    frame = normalise_columns(frame)

    return ReadResult(
        frame=frame,
        options={
            "encoding": encoding_finding.value,
            "column_widths": [list(pair) for pair in colspecs],
            "skip_rows": skip,
            "has_header": bool(overrides.get("has_header", True)),
        },
        findings=[encoding_finding, finding],
    )


def _infer_boundaries(lines: list[str]) -> tuple[list[tuple[int, int]], Finding]:
    """Column edges, from the positions that are blank on nearly every line."""
    sample = lines[:200]
    width = max(len(line) for line in sample)
    # How often each character position is a space. A gap between columns is a
    # position that is a space essentially always; a position inside a text
    # column is a space sometimes, because words have spaces in them.
    blank_rate = [
        sum(1 for line in sample if position >= len(line) or line[position] == " ") / len(sample)
        for position in range(width)
    ]

    gaps: list[tuple[int, int]] = []
    start: int | None = None
    for position, rate in enumerate(blank_rate):
        if rate >= 0.98:
            if start is None:
                start = position
        elif start is not None:
            gaps.append((start, position))
            start = None
    if start is not None:
        gaps.append((start, width))

    boundaries: list[tuple[int, int]] = []
    cursor = 0
    for gap_start, gap_end in gaps:
        if gap_start > cursor:
            boundaries.append((cursor, gap_start))
        cursor = gap_end
    if cursor < width:
        boundaries.append((cursor, width))

    if not boundaries:
        boundaries = [(0, width)]

    return boundaries, Finding(
        stage="column_boundaries",
        value=[list(pair) for pair in boundaries],
        certainty=Certainty.LIKELY if len(boundaries) > 1 else Certainty.UNCERTAIN,
        confidence=0.85 if len(boundaries) > 1 else 0.4,
        reason=(
            f"{count_of(len(boundaries), 'column')} found from positions that are blank on "
            "essentially every line."
        ),
        evidence=sample[:3],
    )
