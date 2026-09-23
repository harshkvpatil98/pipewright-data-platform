"""Producing the file somebody actually opens.

The chore this exists to remove is a person exporting the same spreadsheet every
Monday. That only works if the spreadsheet is *good* -- typed columns, frozen
headers, sensible widths -- because a CSV dumped out of a database is exactly
what they were already doing by hand.

Formats deliberately offered: Excel, CSV, and a self-contained HTML page. Not
PDF: rendering one properly needs a layout engine this deployment does not have,
and a bad PDF is worse than an HTML page that prints correctly.
"""

from __future__ import annotations

import html
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

EXPORT_FORMATS = ("excel", "csv", "html", "pdf")

# Excel's own ceiling is 1,048,576 rows; well before that a spreadsheet stops
# being something a person opens.
MAX_EXPORT_ROWS = 200_000

# Column widths are computed from the content, within these bounds -- narrow
# enough to fit on a screen, wide enough to read.
MIN_COLUMN_WIDTH = 10
MAX_COLUMN_WIDTH = 48


@dataclass
class ExportResult:
    content: bytes
    filename: str
    media_type: str
    row_count: int


def _extension(file_format: str) -> str:
    return {"excel": "xlsx", "csv": "csv", "html": "html", "pdf": "pdf"}[file_format]


def _media_type(file_format: str) -> str:
    return {
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "html": "text/html",
        "pdf": "application/pdf",
    }[file_format]


def safe_filename(title: str, file_format: str) -> str:
    """A filename that survives every operating system it might land on."""
    cleaned = "".join(
        character if character.isalnum() or character in " -_" else "-" for character in title
    ).strip()
    cleaned = "-".join(part for part in cleaned.split() if part) or "report"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{cleaned[:60]}-{stamp}.{_extension(file_format)}"


def export(
    frame: pd.DataFrame,
    *,
    title: str,
    file_format: str = "excel",
    subtitle: str | None = None,
) -> ExportResult:
    if file_format not in EXPORT_FORMATS:
        raise BadRequestError(f"Reports can be produced as: {', '.join(EXPORT_FORMATS)}.")
    if len(frame) > MAX_EXPORT_ROWS:
        raise BadRequestError(
            f"This would be {len(frame):,} rows. Filter it down below {MAX_EXPORT_ROWS:,} "
            "or use a dataset export instead."
        )

    if file_format == "csv":
        content = frame.to_csv(index=False).encode()
    elif file_format == "html":
        content = _render_html(frame, title=title, subtitle=subtitle).encode()
    elif file_format == "pdf":
        content = _render_pdf(frame, title=title, subtitle=subtitle)
    else:
        content = _render_excel(frame, title=title, subtitle=subtitle)

    return ExportResult(
        content=content,
        filename=safe_filename(title, file_format),
        media_type=_media_type(file_format),
        row_count=len(frame),
    )


def _render_excel(frame: pd.DataFrame, *, title: str, subtitle: str | None) -> bytes:
    """A workbook somebody can work in, not a CSV with a different extension."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (title[:28] or "Report").replace("/", "-").replace("\\", "-")

    sheet.append([title])
    sheet["A1"].font = Font(size=14, bold=True)
    row_offset = 2
    if subtitle:
        sheet.append([subtitle])
        sheet["A2"].font = Font(size=10, color="666666")
        row_offset = 3
    sheet.append([])

    header_row = row_offset + 1
    sheet.append([str(column) for column in frame.columns])
    header_fill = PatternFill("solid", fgColor="1F2937")
    for index in range(1, len(frame.columns) + 1):
        cell = sheet.cell(row=header_row, column=index)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for record in frame.itertuples(index=False):
        sheet.append([_excel_value(value) for value in record])

    # Freeze under the header so scrolling a long report keeps the column names
    # visible -- the single thing that makes a big sheet usable.
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    sheet.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(max(len(frame.columns), 1))}"
        f"{header_row + len(frame)}"
    )

    for index, column in enumerate(frame.columns, start=1):
        width = max(
            len(str(column)),
            *(len(str(value)) for value in frame[column].head(200)),
        ) if len(frame) else len(str(column))
        sheet.column_dimensions[get_column_letter(index)].width = max(
            MIN_COLUMN_WIDTH, min(width + 2, MAX_COLUMN_WIDTH)
        )
        if pd.api.types.is_numeric_dtype(frame[column]):
            for row in range(header_row + 1, header_row + 1 + len(frame)):
                sheet.cell(row=row, column=index).number_format = (
                    "#,##0" if pd.api.types.is_integer_dtype(frame[column]) else "#,##0.00"
                )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _excel_value(value: Any) -> Any:
    """Something openpyxl can write without losing what it meant."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            return str(value)
    if isinstance(value, (str, int, float, bool, datetime)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return str(value)


def _render_html(frame: pd.DataFrame, *, title: str, subtitle: str | None) -> str:
    """One self-contained file: no stylesheet to lose, no fonts to fetch.

    It prints to PDF correctly from any browser, which is what people actually
    do with a report they need to send on.
    """
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
    body_rows = []
    for record in frame.head(5000).itertuples(index=False):
        cells = "".join(
            f"<td>{'' if value is None or (isinstance(value, float) and pd.isna(value)) else html.escape(str(value))}</td>"
            for value in record
        )
        body_rows.append(f"<tr>{cells}</tr>")

    truncated_note = (
        f"<p class='note'>Showing the first 5,000 of {len(frame):,} rows.</p>"
        if len(frame) > 5000
        else ""
    )
    generated = datetime.now(UTC).strftime("%d %B %Y at %H:%M UTC")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ font: 14px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; margin: 40px; color: #111827; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub, .note {{ color: #6b7280; font-size: 13px; margin: 0 0 20px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ background: #1f2937; color: #fff; text-align: left; padding: 8px 10px; position: sticky; top: 0; }}
  td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 10px; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  @media print {{ body {{ margin: 12px; }} th {{ position: static; }} }}
</style></head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="sub">{html.escape(subtitle or "")} Generated {generated}.</p>
  {truncated_note}
  <table><thead><tr>{header}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
</body></html>"""


# PDF pages hold this many rows and columns before the table stops being
# readable at the sizes below; the note on the page says what was left out.
PDF_MAX_ROWS = 5_000
PDF_MAX_COLUMNS = 14


def _render_pdf(frame: pd.DataFrame, *, title: str, subtitle: str | None) -> bytes:
    """A paginated PDF with a repeating header row, rendered by reportlab -- a
    maintained, pure-Python layout engine, so this is a real file rather than a
    web page somebody has to print. Wide tables go landscape; anything past the
    column or row cap is stated on the page, never silently dropped."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    columns = [str(column) for column in frame.columns]
    shown_columns = columns[:PDF_MAX_COLUMNS]
    shown = frame[shown_columns].head(PDF_MAX_ROWS)
    notes: list[str] = []
    if len(frame) > PDF_MAX_ROWS:
        notes.append(f"Showing the first {PDF_MAX_ROWS:,} of {len(frame):,} rows.")
    if len(columns) > PDF_MAX_COLUMNS:
        notes.append(
            f"Showing {PDF_MAX_COLUMNS} of {len(columns)} columns; the rest are in the spreadsheet formats."
        )

    def cell(value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        text = str(value)
        return text if len(text) <= 60 else text[:57] + "..."

    rows = [shown_columns] + [[cell(v) for v in record] for record in shown.itertuples(index=False)]
    if len(rows) == 1:
        rows.append(["(no rows)"] + [""] * (len(shown_columns) - 1) if shown_columns else ["(no rows)"])

    page = landscape(A4) if len(shown_columns) > 6 else A4
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=page, title=title, author="Pipewright",
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
    )
    heading = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=15, leading=19)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#6b7280"))
    generated = datetime.now(UTC).strftime("%d %B %Y at %H:%M UTC")
    story: list[Any] = [
        Paragraph(html.escape(title), heading),
        Paragraph(html.escape((subtitle or "").strip() + f" Generated {generated}."), sub),
    ]
    for note in notes:
        story.append(Paragraph(html.escape(note), sub))
    story.append(Spacer(1, 4 * mm))

    font_size = 8 if len(shown_columns) > 8 else 9
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    def footer(canvas, doc) -> None:  # noqa: ANN001 - reportlab callback signature
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(page[0] - 14 * mm, 8 * mm, f"Page {doc.page}")
        canvas.drawString(14 * mm, 8 * mm, html.unescape(title)[:90])
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
