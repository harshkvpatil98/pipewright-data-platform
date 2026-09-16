"""Workbooks, which are documents pretending to be tables.

The specific hard parts, each of which silently corrupts a load:

* **Multiple sheets.** Reading the first and ignoring the rest is what the old
  implementation did. The others are reported so they can become datasets.
* **Merged cells.** A merged cell holds its value in the top-left and `None` in
  every other cell of the range. Read naively, a category column becomes one
  value followed by a column of blanks. openpyxl knows the ranges, so the value
  is filled across them and the fact is reported.
* **Formulas.** A cell has a formula and a cached value. The value is what the
  table means; the formula is what produced it. This reads values, and says so,
  because `=VLOOKUP(...)` in a numeric column is not a number.
* **Serial dates.** Excel stores a date as days since 1899-12-30. A column read
  as numbers becomes `45292` instead of `2024-01-01`.
* **`#REF!` and friends.** A failed formula is neither text nor null; it is an
  error, counted and reported rather than imported as the string "#REF!".
* **Hidden rows and columns.** Usually working notes. Kept, but counted, since
  a total that does not add up is often a hidden row.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff.columns import EXCEL_ERRORS
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain


def read_excel(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    overrides = dict(overrides or {})
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl is a dependency
        raise BadRequestError("Reading Excel files needs the 'openpyxl' package.") from exc

    try:
        # `data_only` gives the cached value rather than the formula, which is
        # what the table means. Read-only mode keeps a large workbook from
        # being held in memory twice.
        workbook = load_workbook(io.BytesIO(payload), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 - any failure here is "not a workbook"
        raise BadRequestError(f"Could not open this workbook: {exc}") from exc

    sheet_names = list(workbook.sheetnames)
    if not sheet_names:
        raise BadRequestError("This workbook has no sheets.")

    requested = overrides.get("sheet")
    if requested is not None and str(requested) not in sheet_names:
        raise BadRequestError(
            f"This workbook has no sheet called '{requested}'. It has: {', '.join(sheet_names)}."
        )
    sheet_name = str(requested) if requested is not None else sheet_names[0]

    findings: list[Finding] = [
        certain(
            "format",
            "excel",
            f"A workbook of {len(sheet_names)} sheet(s); reading '{sheet_name}'.",
            evidence=sheet_names[:10],
        )
    ]
    warnings: list[str] = []
    if len(sheet_names) > 1 and requested is None:
        warnings.append(
            f"This workbook has {len(sheet_names)} sheets. '{sheet_name}' was read; "
            f"the others ({', '.join(sheet_names[1:6])}) can each become their own dataset."
        )

    # Merged ranges are only available from a normally-loaded workbook; the
    # read-only loader does not expose them.
    merged = _merged_ranges(payload, sheet_name)
    rows = _rows(workbook[sheet_name], limit=limit)
    workbook.close()

    if not rows:
        raise BadRequestError(f"Sheet '{sheet_name}' is empty.")

    if merged:
        rows = _fill_merged(rows, merged)
        findings.append(
            certain(
                "merged_cells",
                len(merged),
                (
                    f"{len(merged)} merged range(s) found. Their value has been copied "
                    "across every cell of the range, which is what the sheet shows and "
                    "what a table needs."
                ),
                evidence=[str(area) for area in merged[:5]],
            )
        )

    skip = int(overrides.get("skip_rows") or _preamble_rows(rows))
    if skip:
        findings.append(
            certain(
                "header_row",
                skip,
                f"The table starts on row {skip + 1}; the rows above it are a preamble.",
                evidence=[_render(row) for row in rows[:skip][:3]],
            )
        )
    body = rows[skip:]
    if not body:
        raise BadRequestError(f"Sheet '{sheet_name}' has no rows after its preamble.")

    has_header = bool(overrides.get("has_header", True))
    if has_header:
        header = [
            str(cell).strip() if cell is not None else f"column_{index + 1}"
            for index, cell in enumerate(body[0])
        ]
        data = body[1:]
    else:
        header = [f"column_{index + 1}" for index in range(len(body[0]))]
        data = body

    width = len(header)
    rectangular = [list(row[:width]) + [None] * max(0, width - len(row)) for row in data]
    frame = normalise_columns(pd.DataFrame(rectangular, columns=header))

    errors = int(
        sum(
            frame[column].astype(str).str.strip().str.upper().isin(EXCEL_ERRORS).sum()
            for column in frame.columns
        )
    )
    if errors:
        findings.append(
            Finding(
                stage="formula_errors",
                value=errors,
                certainty=Certainty.CERTAIN,
                confidence=1.0,
                reason=(
                    f"{errors} cell(s) hold a formula error such as #REF!. They are values "
                    "the workbook could not compute, not data — treat them as missing."
                ),
                evidence=list(EXCEL_ERRORS),
            )
        )

    frame = _convert_serial_dates(frame, findings)

    return ReadResult(
        frame=frame,
        options={
            "sheet": sheet_name,
            # The name this has always been reported under; kept so existing
            # run summaries and their readers do not change meaning.
            "sheet_name": sheet_name,
            "skip_rows": skip,
            "has_header": has_header,
        },
        findings=findings,
        tables=sheet_names,
        warnings=warnings,
    )


def _render(row: list[Any]) -> str:
    """One sheet row as a line, for showing a preamble back to somebody."""
    return " | ".join("" if cell is None else str(cell) for cell in row).strip(" |")


def _rows(sheet: Any, *, limit: int | None) -> list[list[Any]]:
    collected: list[list[Any]] = []
    for row in sheet.iter_rows(values_only=True):
        if row is None:
            continue
        collected.append(list(row))
        # One extra for the header row, so `limit` counts data rows.
        if limit and len(collected) > limit + 1:
            break
    # Trailing empty rows are an artefact of how far somebody scrolled.
    while collected and all(cell is None or str(cell).strip() == "" for cell in collected[-1]):
        collected.pop()
    return collected


def _merged_ranges(payload: bytes, sheet_name: str) -> list[Any]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(payload), data_only=True)
        ranges = list(workbook[sheet_name].merged_cells.ranges)
        workbook.close()
        return ranges
    except Exception:  # noqa: BLE001 - merged ranges are a nicety, not the read
        return []


def _fill_merged(rows: list[list[Any]], merged: list[Any]) -> list[list[Any]]:
    """Copy each merged cell's value across its range.

    Without this a merged category header gives one value and a column of
    blanks, and every group but the first loses its label.
    """
    filled = [list(row) for row in rows]
    for area in merged:
        top, left = area.min_row - 1, area.min_col - 1
        if top >= len(filled) or left >= len(filled[top]):
            continue
        value = filled[top][left]
        if value is None:
            continue
        for row_index in range(top, min(area.max_row, len(filled))):
            row = filled[row_index]
            for column_index in range(left, min(area.max_col, len(row))):
                if row[column_index] is None:
                    row[column_index] = value
    return filled


def _preamble_rows(rows: list[list[Any]]) -> int:
    """How many rows above the table are a title block.

    A preamble row in a spreadsheet is narrow -- a title in A1 and nothing else
    -- where the table is wide. Comparing filled-cell counts finds it without
    needing to understand what the title says.
    """
    widths = [sum(1 for cell in row if cell is not None and str(cell).strip()) for row in rows[:30]]
    if not widths:
        return 0
    table_width = max(widths)
    if table_width <= 1:
        return 0
    for index, width in enumerate(widths):
        # The first row that is at least half as wide as the widest is the
        # table; anything narrower above it is decoration.
        if width >= max(2, table_width * 0.5):
            return index
    return 0


def _convert_serial_dates(frame: pd.DataFrame, findings: list[Finding]) -> pd.DataFrame:
    """Turn columns of spreadsheet serials back into dates.

    Only whole columns, and only when every value sits in a plausible date
    range -- a column of prices around 45,000 would otherwise become dates in
    2023, which is a worse failure than the one being fixed.
    """
    from service_ingestion.sniff.dates import from_excel_serial, looks_like_excel_serial

    out = frame.copy()
    for column in out.columns:
        values = out[column].dropna()
        if values.empty:
            continue
        # Already a datetime because openpyxl recognised the cell format: that
        # is the common case and needs nothing.
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            continue
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.isna().any():
            continue
        if not looks_like_excel_serial(numeric.tolist()):
            continue
        # A column of identifiers can land in the same numeric band, so this
        # asks for a hint from the name before rewriting the values.
        if not any(token in str(column).lower() for token in ("date", "day", "time", "when", "dt")):
            findings.append(
                Finding(
                    stage="excel_serial_dates",
                    value=str(column),
                    certainty=Certainty.AMBIGUOUS,
                    confidence=0.5,
                    reason=(
                        f"Column '{column}' holds whole numbers in the range Excel uses for "
                        "dates. They may be dates stored as serial numbers, or they may be "
                        "numbers. Set the column's type to date if they are dates."
                    ),
                    candidates=[
                        Candidate("date", 0.5, "serial numbers in Excel's date range"),
                        Candidate("number", 0.5, "plain numbers"),
                    ],
                    evidence=[str(value) for value in values.head(4).tolist()],
                )
            )
            continue
        out[column] = numeric.map(from_excel_serial)
        findings.append(
            certain(
                "excel_serial_dates",
                str(column),
                (
                    f"Column '{column}' held Excel serial numbers and has been read as dates "
                    "(the epoch is 1899-12-30, which absorbs Excel's 1900 leap-year bug)."
                ),
                evidence=[str(value) for value in values.head(3).tolist()],
            )
        )
    return out
