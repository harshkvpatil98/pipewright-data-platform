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
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff import pipeline
from service_ingestion.sniff.delimiter import count_fields
from service_ingestion.sniff.evidence import Certainty, Finding, certain

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

    lines = text.splitlines()
    body = lines[layout.skip_rows:]
    if not body:
        raise BadRequestError("There are no rows after the header.")

    expected = len(layout.columns) if layout.columns else None
    ragged: list[tuple[int, int]] = []
    kept: list[str] = []
    for offset, line in enumerate(body):
        if not line.strip():
            continue
        if expected and offset > 0:
            width = count_fields(line, dialect.delimiter, dialect.quote_char, dialect.escape_char)
            # A trailing delimiter produces one extra empty field on every row;
            # that is a dialect quirk rather than a ragged row.
            if width != expected and not (width == expected + 1 and line.rstrip().endswith(dialect.delimiter)):
                ragged.append((layout.skip_rows + offset + 1, width))
        kept.append(line)
        if limit and len(kept) > limit + 1:
            break

    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(FIELD_LIMIT)
        # The names come from `header.py`, which has already made them distinct
        # and usable. Letting pandas dedupe instead produces `amount.1`, which
        # looks like a real column name and is not the one the file used.
        frame = pd.read_csv(
            io.StringIO("\n".join(kept)),
            sep=dialect.delimiter,
            quotechar=dialect.quote_char,
            escapechar=dialect.escape_char,
            header=None,
            names=layout.columns or None,
            skiprows=1 if layout.has_header else 0,
            dtype=str,
            keep_default_na=False,
            na_values=[],
            engine="python",
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
                    f"{len(ragged)} row(s) do not have {expected} fields and were skipped. "
                    "A footer total or a stray delimiter usually explains it."
                ),
                evidence=[sample],
            )
        )
        warnings.append(f"{len(ragged)} ragged row(s) were skipped.")
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
            f"{len(boundaries)} column(s) found from positions that are blank on "
            "essentially every line."
        ),
        evidence=sample[:3],
    )
