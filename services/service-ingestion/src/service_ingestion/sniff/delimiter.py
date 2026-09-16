"""Which character separates the fields.

The naive method -- count characters in the first line, pick the commonest --
gets semicolon files wrong whenever a description field contains a comma, and
gets every file wrong whose first line is a title. So the test here is
**consistency across lines**, which is the property a real delimiter has and a
character that merely appears often does not: a delimiter produces the *same*
field count on every data row.

Quoting has to be respected while counting, or a single `"Smith, John"` makes
the comma look inconsistent and hands the file to the semicolon.

`csv.Sniffer` exists and is not used: it raises on files it cannot read rather
than ranking what it considered, it ignores the possibility of a preamble, and
it cannot report why. Ranked candidates with scores are the whole point here.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any

from service_ingestion.sniff.evidence import (
    Candidate,
    Certainty,
    Finding,
    certain,
    from_candidates,
)

#: The separators worth considering, with the names people use for them.
CANDIDATES: tuple[tuple[str, str], ...] = (
    (",", "comma"),
    (";", "semicolon"),
    ("\t", "tab"),
    ("|", "pipe"),
    ("\x01", "SOH (Hive default)"),
    ("~", "tilde"),
    (":", "colon"),
)

#: How many lines are examined. Enough for consistency to mean something,
#: bounded so a huge file costs the same as a small one.
SAMPLE_LINES = 200


@dataclass
class DialectResult:
    delimiter: str
    quote_char: str
    #: True when a quote inside a quoted field is written `\"` rather than `""`.
    escape_char: str | None
    finding: Finding
    quote_finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {
            "delimiter": self.delimiter,
            "quote_char": self.quote_char,
            "escape_char": self.escape_char,
            "finding": self.finding.to_dict(),
            "quote_finding": self.quote_finding.to_dict(),
        }


def split_lines(text: str, *, limit: int = SAMPLE_LINES) -> list[str]:
    """Physical lines, without the ones that are only whitespace.

    Physical rather than logical: a quoted field containing a newline spans two
    physical lines, which is exactly the case `count_fields` has to survive, and
    joining them here would hide it.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            lines.append(raw)
        if len(lines) >= limit:
            break
    return lines


def count_fields(line: str, delimiter: str, quote: str = '"', escape: str | None = None) -> int:
    """Fields in one line, counting only delimiters outside quotes."""
    if not line:
        return 0
    fields = 1
    inside = False
    index = 0
    while index < len(line):
        character = line[index]
        if escape and character == escape and index + 1 < len(line):
            index += 2
            continue
        if character == quote:
            # A doubled quote inside a quoted field is one literal quote, not
            # the end of the field -- `"she said ""hi"""` is a single value.
            if inside and index + 1 < len(line) and line[index + 1] == quote:
                index += 2
                continue
            inside = not inside
        elif character == delimiter and not inside:
            fields += 1
        index += 1
    return fields


def _score(lines: list[str], delimiter: str, quote: str, escape: str | None) -> tuple[float, str, list[int]]:
    counts = [count_fields(line, delimiter, quote, escape) for line in lines]
    useful = [count for count in counts if count > 1]
    if not useful:
        return 0.0, "never appears outside quotes", counts

    average = mean(useful)
    spread = pstdev(useful) if len(useful) > 1 else 0.0

    # Consistency is the signal. A delimiter giving 7 fields on every line is
    # the delimiter; one giving 3, 9, 2, 14 is a character that happens to occur.
    consistency = 1.0 / (1.0 + spread)
    coverage = len(useful) / len(counts)
    # More fields is weakly better -- it discriminates between a real delimiter
    # and one that splits a line in two by coincidence -- but only weakly, or a
    # colon inside timestamps would beat a comma.
    richness = min((average - 1) / 8.0, 1.0)

    score = 0.6 * consistency + 0.3 * coverage + 0.1 * richness
    reason = (
        f"{average:.1f} fields per line on average, "
        + ("identical on every line" if spread == 0 else f"varying by {spread:.1f}")
        + f", present on {coverage:.0%} of lines"
    )
    return score, reason, counts


def detect_quote(lines: list[str]) -> Finding:
    """Whether fields are wrapped in `"` or `'`, and how an inner quote is written."""
    double = sum(line.count('"') for line in lines)
    single = sum(line.count("'") for line in lines)

    if double == 0 and single == 0:
        return certain("quote_char", '"', "No quoting in the sample; the default applies.")
    if double >= single:
        return certain(
            "quote_char", '"', f'Double quotes appear {double} times in the sample.'
        )
    # Apostrophes in prose (`it's`) outnumber real single-quoting often enough
    # that this is worth flagging rather than applying.
    return Finding(
        stage="quote_char",
        value="'",
        certainty=Certainty.UNCERTAIN,
        confidence=0.6,
        reason=(
            f"Single quotes appear {single} times against {double} double quotes. "
            "Apostrophes in text look the same, so this is worth confirming."
        ),
        candidates=[
            Candidate("'", 0.6, f"{single} occurrences"),
            Candidate('"', 0.4, f"{double} occurrences"),
        ],
        evidence=[line for line in lines if "'" in line][:3],
    )


def detect(text: str) -> DialectResult:
    """The delimiter, the quote character, and the evidence for both."""
    lines = split_lines(text)
    if not lines:
        return DialectResult(
            delimiter=",",
            quote_char='"',
            escape_char=None,
            finding=Finding(
                stage="delimiter",
                value=",",
                certainty=Certainty.UNCERTAIN,
                confidence=0.0,
                reason="The file has no non-blank lines to examine.",
            ),
            quote_finding=certain("quote_char", '"', "Nothing to examine."),
        )

    quote_finding = detect_quote(lines)
    quote = str(quote_finding.value)

    # A backslash before a quote means the file escapes rather than doubles.
    escape = "\\" if any('\\"' in line or "\\'" in line for line in lines) else None

    candidates: list[Candidate] = []
    evidence = lines[:3]
    for delimiter, name in CANDIDATES:
        score, reason, counts = _score(lines, delimiter, quote, escape)
        if score <= 0:
            continue
        candidates.append(Candidate(delimiter, score, f"{name}: {reason}"))

    finding = from_candidates(
        "delimiter",
        candidates,
        reason="Chosen by how consistently it splits every line into the same number of fields.",
        evidence=evidence,
        fallback=",",
        blocking_when_ambiguous=False,
    )
    # A single-column file is a real thing -- one column of ids, a log. Saying
    # "comma, 0% confidence" about it is worse than saying what it is.
    if not candidates:
        finding = certain(
            "delimiter",
            ",",
            "No separator divides these lines consistently; reading as a single column.",
            evidence=evidence,
        )

    return DialectResult(
        delimiter=str(finding.value),
        quote_char=quote,
        escape_char=escape,
        finding=finding,
        quote_finding=quote_finding,
    )
