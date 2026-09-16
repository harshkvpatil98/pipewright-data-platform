"""Which month is `03/04/2026`?

In London it is April. In New York it is March. Both readings parse, both
produce a valid table, and the difference only surfaces as numbers landing in
the wrong quarter — usually months later, usually in a report somebody has
already sent.

So this module never picks a default. It scans the **whole column** for a value
that settles it — any day past the twelfth proves which position is the day —
and if no such value exists it returns `AMBIGUOUS` and the pipeline asks. That
is the roadmap's requirement stated exactly: *never default to US format
silently*.

The subtle part is that a *sample* is not good enough. A column of a thousand
dates where the only disambiguating value is row 900 is a column the naive
implementation gets wrong. The scan is therefore over every value, stopping the
moment one of them proves the point — which is cheap in the common case and
correct in the rare one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: Formats tried, in the order they are considered. Unambiguous ones first, so
#: an ISO date is never reported as a coin-flip between two readings.
FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "ISO 8601 (year first)"),
    ("%Y/%m/%d", "year first with slashes"),
    ("%Y-%m-%dT%H:%M:%S", "ISO 8601 date and time"),
    ("%Y-%m-%d %H:%M:%S", "year first, date and time"),
    ("%d/%m/%Y", "day first (most of the world)"),
    ("%m/%d/%Y", "month first (United States)"),
    ("%d-%m-%Y", "day first with dashes"),
    ("%m-%d-%Y", "month first with dashes"),
    ("%d.%m.%Y", "day first with dots (Europe)"),
    ("%m.%d.%Y", "month first with dots"),
    ("%d/%m/%y", "day first, two-digit year"),
    ("%m/%d/%y", "month first, two-digit year"),
    ("%d %b %Y", "day, abbreviated month name, year"),
    ("%d %B %Y", "day, month name, year"),
    ("%b %d, %Y", "abbreviated month name, day, year"),
    ("%B %d, %Y", "month name, day, year"),
    ("%Y%m%d", "compact year first"),
)

#: Pairs that read the same bytes differently. These are the ones that need a
#: disambiguating value before either can be claimed.
RIVALS: dict[str, str] = {
    "%d/%m/%Y": "%m/%d/%Y",
    "%m/%d/%Y": "%d/%m/%Y",
    "%d-%m-%Y": "%m-%d-%Y",
    "%m-%d-%Y": "%d-%m-%Y",
    "%d.%m.%Y": "%m.%d.%Y",
    "%m.%d.%Y": "%d.%m.%Y",
    "%d/%m/%y": "%m/%d/%y",
    "%m/%d/%y": "%d/%m/%y",
}

#: `03/04/2026` shaped: two small numbers and a year, in some order.
_SLASHED = re.compile(r"^\s*(\d{1,2})([/\-.])(\d{1,2})\2(\d{2}|\d{4})\s*$")

#: Excel keeps dates as days since 1899-12-30. A column of numbers in this band
#: that a spreadsheet produced is almost certainly dates, and reading them as
#: integers turns a date column into meaningless five-digit numbers.
EXCEL_EPOCH_MIN = 20_000   # 1954
EXCEL_EPOCH_MAX = 60_000   # 2064


@dataclass
class DateResult:
    """What a column of date-looking strings turned out to be."""

    #: The `strftime` format, or None when nothing parsed.
    fmt: str | None
    finding: Finding
    #: Values that did not parse under the chosen format.
    rejected: list[str] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return self.finding.certainty is Certainty.AMBIGUOUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.fmt,
            "finding": self.finding.to_dict(),
            "rejected": list(self.rejected[:10]),
        }


def looks_like_date(value: str) -> bool:
    text = value.strip()
    if not text or len(text) > 40:
        return False
    if _SLASHED.match(text):
        return True
    return bool(re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", text)) or bool(
        re.match(r"^\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}$", text)
    )


def _parses(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value.strip(), fmt)
        return True
    except (ValueError, TypeError):
        return False


def disambiguating_value(values: Iterable[str]) -> tuple[str, int] | None:
    """The first value that proves which position holds the day.

    Returns the value and which component was greater than twelve: 1 for the
    first number, 3 for the third. Scanning every value rather than a sample,
    because the one value that settles a thousand-row column is exactly the one
    a sample misses.
    """
    for raw in values:
        match = _SLASHED.match(str(raw))
        if not match:
            continue
        first, _, second = int(match.group(1)), match.group(2), int(match.group(3))
        if first > 12 and second <= 12:
            return str(raw), 1
        if second > 12 and first <= 12:
            return str(raw), 3
    return None


def detect(values: Iterable[str], *, column: str = "") -> DateResult:
    """The format of a column of dates, or an honest refusal to choose."""
    sample = [str(value).strip() for value in values if str(value).strip()]
    if not sample:
        return DateResult(
            fmt=None,
            finding=Finding(
                stage="date_format",
                value=None,
                certainty=Certainty.UNCERTAIN,
                confidence=0.0,
                reason="The column is empty.",
            ),
        )

    scored: list[tuple[str, str, float]] = []
    for fmt, label in FORMATS:
        matched = sum(1 for value in sample if _parses(value, fmt))
        if matched:
            scored.append((fmt, label, matched / len(sample)))

    if not scored:
        return DateResult(
            fmt=None,
            finding=Finding(
                stage="date_format",
                value=None,
                certainty=Certainty.UNCERTAIN,
                confidence=0.0,
                reason="No known date format reads these values.",
                evidence=sample[:5],
            ),
        )

    scored.sort(key=lambda item: item[2], reverse=True)
    best_fmt, best_label, best_rate = scored[0]

    rival = RIVALS.get(best_fmt)
    rival_rate = next((rate for fmt, _, rate in scored if fmt == rival), 0.0)

    # Only a genuine rival that reads the same values needs disambiguating.
    if rival and rival_rate >= best_rate * 0.999:
        proof = disambiguating_value(sample)
        if proof is not None:
            value, position = proof
            day_first = position == 1
            chosen = best_fmt if _day_first(best_fmt) == day_first else rival
            label = dict((fmt, name) for fmt, name, _ in scored).get(chosen, chosen)
            rejected = [item for item in sample if not _parses(item, chosen)]
            return DateResult(
                fmt=chosen,
                finding=certain(
                    "date_format",
                    chosen,
                    (
                        f"'{value}' has {'a day' if day_first else 'a month'} past the "
                        f"twelfth in the {'first' if position == 1 else 'second'} position, "
                        f"which settles it: {label}."
                    ),
                    evidence=[value] + sample[:3],
                ),
                rejected=rejected,
            )

        # Nothing in the column settles it, so the file genuinely does not say.
        both = [
            Candidate(best_fmt, best_rate, _describe(best_fmt)),
            Candidate(rival, rival_rate, _describe(rival)),
        ]
        first = sample[0]
        return DateResult(
            fmt=None,
            finding=Finding(
                stage="date_format",
                value=None,
                certainty=Certainty.AMBIGUOUS,
                confidence=best_rate,
                reason=(
                    f"{('Column ' + column + ': ') if column else ''}"
                    f"'{first}' could be {_example(first, best_fmt)} or "
                    f"{_example(first, rival)}. No value in this column has a day past "
                    "the twelfth, so the file does not say which. Choose the format."
                ),
                candidates=both,
                evidence=sample[:6],
                blocking=True,
            ),
        )

    rejected = [value for value in sample if not _parses(value, best_fmt)]
    certainty = Certainty.CERTAIN if best_rate == 1.0 and not rival else (
        Certainty.LIKELY if best_rate >= 0.95 else Certainty.UNCERTAIN
    )
    return DateResult(
        fmt=best_fmt,
        finding=Finding(
            stage="date_format",
            value=best_fmt,
            certainty=certainty,
            confidence=best_rate,
            reason=(
                f"{best_rate:.1%} of values read as {best_label}"
                + (f"; {len(rejected)} did not" if rejected else "")
                + "."
            ),
            candidates=[Candidate(fmt, rate, label) for fmt, label, rate in scored[:4]],
            evidence=sample[:4] + (["rejected: " + ", ".join(rejected[:3])] if rejected else []),
        ),
        rejected=rejected,
    )


def _day_first(fmt: str) -> bool:
    return fmt.startswith("%d")


def _describe(fmt: str) -> str:
    return dict(FORMATS).get(fmt, fmt)


def _example(value: str, fmt: str) -> str:
    """The same string, read under one format and written out in words."""
    try:
        parsed = datetime.strptime(value.strip(), fmt)
    except (ValueError, TypeError):
        return f"unreadable as {fmt}"
    return parsed.strftime("%-d %B %Y") if hasattr(parsed, "strftime") else str(parsed)


def looks_like_excel_serial(values: Iterable[float]) -> bool:
    """Whether a numeric column is really spreadsheet dates.

    Excel writes a date as the number of days since 1899-12-30. Read as an
    integer it is a plausible-looking five-digit number, which is why a column
    of them silently becomes `45292` instead of `2024-01-01`.
    """
    numbers = [value for value in values if value is not None]
    if len(numbers) < 3:
        return False
    return all(EXCEL_EPOCH_MIN <= float(value) <= EXCEL_EPOCH_MAX for value in numbers)


def from_excel_serial(serial: float) -> datetime:
    """A spreadsheet serial as a date.

    The epoch is 1899-12-30, not 1899-12-31: Lotus 1-2-3 believed 1900 was a
    leap year, Excel copied the bug for compatibility, and every serial past
    February 1900 is off by one unless the epoch absorbs it.
    """
    from datetime import timedelta

    return datetime(1899, 12, 30) + timedelta(days=float(serial))
