"""Where the table actually starts.

Files with a preamble are not an edge case; in finance they are the norm. A
bank export opens with the account name, the statement period, a blank line,
and *then* the header. Reading row zero as the header gives one column called
"Statement for account 0012345678" and loses every real column name.

The test is the one the roadmap names: find the first row after which the type
profile of subsequent rows becomes **stable**. A preamble line has a different
shape from the data -- fewer fields, all text, often a single cell. The header
itself is the row that is all text immediately above rows that are not.

Two failure modes this is careful about:

* **A file with no header at all.** Sensor exports and database dumps often
  start straight into data. Inventing column names from the first data row
  silently loses a row and mislabels every column, so "no header" is a real
  answer here, not a fallback.
* **A file whose data is all text.** Then "all text above non-text" proves
  nothing, and the decision rests on uniqueness and field count instead --
  reported with lower confidence, because that is what it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from service_ingestion.sniff.delimiter import count_fields
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: How far into the file a header may be. Past this it is not a preamble, it is
#: a different file with something appended.
MAX_PREAMBLE_LINES = 30

_NUMBER = re.compile(r"^[+-]?[\d\s.,']*\d[\d\s.,']*$")
_DATEISH = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
_BOOL = {"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"}


@dataclass
class HeaderResult:
    #: Lines to skip before the header. 0 means the file starts with it.
    skip_rows: int
    #: False when the file has no header row and columns must be positional.
    has_header: bool
    columns: list[str]
    finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {
            "skip_rows": self.skip_rows,
            "has_header": self.has_header,
            "columns": list(self.columns),
            "finding": self.finding.to_dict(),
        }


def _cells(line: str, delimiter: str, quote: str) -> list[str]:
    """Split one line, honouring quotes, and strip the quoting."""
    cells: list[str] = []
    current: list[str] = []
    inside = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == quote:
            if inside and index + 1 < len(line) and line[index + 1] == quote:
                current.append(quote)
                index += 2
                continue
            inside = not inside
        elif character == delimiter and not inside:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _looks_textual(value: str) -> bool:
    """True when this cell could be a column name rather than a measurement."""
    text = value.strip().strip("\"'")
    if not text:
        return False
    if _NUMBER.match(text) or _DATEISH.match(text):
        return False
    return text.lower() not in _BOOL


def _row_text_ratio(cells: list[str]) -> float:
    filled = [cell for cell in cells if cell.strip()]
    if not filled:
        return 0.0
    return sum(1 for cell in filled if _looks_textual(cell)) / len(filled)


def detect(
    text: str, *, delimiter: str, quote: str = '"', sample_lines: int = 60
) -> HeaderResult:
    """Which line is the header, or that there is not one."""
    lines = [line for line in text.splitlines()[: sample_lines + MAX_PREAMBLE_LINES]]
    non_blank = [(index, line) for index, line in enumerate(lines) if line.strip()]
    if not non_blank:
        return HeaderResult(
            skip_rows=0,
            has_header=False,
            columns=[],
            finding=Finding(
                stage="header_row",
                value=0,
                certainty=Certainty.UNCERTAIN,
                confidence=0.0,
                reason="The file has no non-blank lines.",
            ),
        )

    # The body's field count is the modal count: a preamble is by definition a
    # minority shape. Ties are broken towards the *wider* shape, because a
    # short file can have as many preamble lines as data rows -- a two-line
    # header block above a single row of data is exactly that -- and picking
    # the narrower one makes the preamble the table and loses every column.
    counts = [count_fields(line, delimiter, quote) for _, line in non_blank]
    modal = max(set(counts), key=lambda width: (counts.count(width), width))

    candidates: list[Candidate] = []
    evidence: list[str] = []
    for position, (line_index, line) in enumerate(non_blank[:MAX_PREAMBLE_LINES]):
        fields = counts[position]
        if fields != modal:
            evidence.append(f"line {line_index + 1}: {fields} fields, not {modal} — preamble")
            continue

        cells = _cells(line, delimiter, quote)
        header_ratio = _row_text_ratio(cells)
        following = [
            _row_text_ratio(_cells(candidate_line, delimiter, quote))
            for _, candidate_line in non_blank[position + 1: position + 11]
            if count_fields(candidate_line, delimiter, quote) == modal
        ]
        if not following:
            continue
        body_ratio = sum(following) / len(following)

        blank_names = sum(1 for cell in cells if not cell.strip())
        unique = len({cell.strip().lower() for cell in cells if cell.strip()})
        uniqueness = unique / max(len(cells), 1)

        # A header is text where the body is not. That difference is the signal;
        # the absolute ratio is not, because an all-text table has both at 1.0.
        separation = max(0.0, header_ratio - body_ratio)
        score = 0.55 * separation + 0.25 * header_ratio + 0.2 * uniqueness
        if blank_names:
            score -= 0.15 * (blank_names / max(len(cells), 1))
        # Later rows are worse candidates: the first plausible header is the
        # header, or a file whose second row repeats the names picks the second.
        score -= 0.02 * position

        candidates.append(
            Candidate(
                line_index,
                max(0.0, min(1.0, score)),
                (
                    f"line {line_index + 1}: {header_ratio:.0%} of cells are text "
                    f"against {body_ratio:.0%} below, {unique} distinct names"
                ),
            )
        )

    if not candidates:
        # One non-blank line and nothing under it is a header with no rows --
        # a real export of nothing, which happens whenever a filter matched
        # none. Calling it a row of data loses the column names and invents a
        # row that is not in the file.
        if len(non_blank) == 1:
            line = non_blank[0][1]
            return HeaderResult(
                skip_rows=0,
                has_header=True,
                columns=_dedupe(_cells(line, delimiter, quote)),
                finding=certain(
                    "header_row",
                    0,
                    "One line, and nothing under it: a header with no rows.",
                    evidence=[line],
                ),
            )
        return _headerless(non_blank, delimiter, quote, modal, "no line has the table's shape")

    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    best = ranked[0]

    # A file with no header: the best candidate is not meaningfully more
    # header-like than the rows beneath it.
    if best.score < 0.35:
        return _headerless(
            non_blank, delimiter, quote, modal,
            "no row is more name-like than the rows below it",
            candidates=ranked,
        )

    line_index = int(best.value)
    by_line = dict(non_blank)
    columns = _dedupe(_cells(by_line[line_index], delimiter, quote))

    certainty = (
        Certainty.LIKELY if best.score >= 0.6
        else Certainty.UNCERTAIN
    )
    if len(ranked) > 1 and ranked[1].score > 0 and ranked[1].score / best.score >= 0.95:
        certainty = Certainty.AMBIGUOUS

    return HeaderResult(
        skip_rows=line_index,
        has_header=True,
        columns=columns,
        finding=Finding(
            stage="header_row",
            value=line_index,
            certainty=certainty,
            confidence=best.score,
            reason=(
                f"Header on line {line_index + 1}"
                + (f", after {line_index} line(s) of preamble" if line_index else "")
                + f". {best.reason.split(': ', 1)[-1]}."
            ),
            candidates=ranked[:4],
            evidence=evidence[:5] + [by_line[line_index]],
        ),
    )


def _headerless(
    non_blank: list[tuple[int, str]],
    delimiter: str,
    quote: str,
    modal: int,
    why: str,
    *,
    candidates: list[Candidate] | None = None,
) -> HeaderResult:
    """No header row, so columns are positional.

    Naming them `column_1…column_n` rather than borrowing the first data row:
    borrowing loses a row of real data and labels every column with a value.
    """
    first = next(
        (line for _, line in non_blank if count_fields(line, delimiter, quote) == modal),
        non_blank[0][1],
    )
    width = len(_cells(first, delimiter, quote))
    return HeaderResult(
        skip_rows=0,
        has_header=False,
        columns=[f"column_{index + 1}" for index in range(width)],
        finding=Finding(
            stage="header_row",
            value=None,
            certainty=Certainty.LIKELY,
            confidence=0.7,
            reason=(
                f"This file appears to have no header row — {why}. Columns are "
                f"numbered; rename them, or say which line holds the names."
            ),
            candidates=candidates[:3] if candidates else [],
            evidence=[line for _, line in non_blank[:3]],
        ),
    )


def _dedupe(names: list[str]) -> list[str]:
    """Column names that are usable and distinct.

    Two columns called `amount` is common in exports that join two tables, and
    silently keeping both means one of them is unreachable.
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for index, raw in enumerate(names):
        name = raw.strip().strip("\"'") or f"column_{index + 1}"
        key = name.lower()
        if key in seen:
            seen[key] += 1
            name = f"{name}_{seen[key]}"
        else:
            seen[key] = 1
        out.append(name)
    return out
