"""What each column is, and which values disagree.

Type inference that reports "99.8% integer" without the 0.2% is the reason
people distrust it. The eight values that are not integers are the interesting
ones: they are a footer total, a `N/A`, a thousands separator nobody expected,
or a genuine data-quality problem — and each needs a different response.

So every column carries the values that did not fit, and the null tokens that
were treated as missing are named rather than assumed. `-` means "nothing" in
one export and "negative" in another; guessing is how a column of amounts
quietly loses its negatives.

Types land in Phase 08's lattice, so an ingested column and a warehouse column
are described in the same vocabulary rather than two that nearly agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from shared_python.types import PWType
from shared_python.types import lattice as pw

from service_ingestion.sniff import dates, numbers
from service_ingestion.sniff.evidence import Candidate, Certainty, Finding

#: Strings that conventionally mean "no value". Matched case-insensitively.
#: `-` and `0` are deliberately absent: `-` is a minus sign often enough, and a
#: `0` that becomes null turns a real measurement into a gap.
NULL_TOKENS = (
    "", "na", "n/a", "n.a.", "null", "nil", "none", "nan", "#n/a", "#na",
    "missing", "unknown", "\\n", "-99", "undefined",
)

#: Excel's error values. They are not text and not null: they are a formula
#: that failed, which is worth surfacing rather than importing as a string.
EXCEL_ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!", "#N/A")

TRUE_TOKENS = ("true", "yes", "y", "t", "1")
FALSE_TOKENS = ("false", "no", "n", "f", "0")

#: How many non-conforming values are kept per column.
MAX_REJECTED = 20


@dataclass
class ColumnProfile:
    """One column: what it is, how sure, and what did not fit."""

    name: str
    pw_type: PWType
    finding: Finding
    null_tokens: list[str] = field(default_factory=list)
    #: Values that did not parse as the chosen type, with how often each occurs.
    rejected: list[tuple[str, int]] = field(default_factory=list)
    #: Set for date columns.
    date_format: str | None = None
    #: Set for numeric columns.
    number_format: dict[str, Any] | None = None
    excel_errors: int = 0
    null_count: int = 0
    total: int = 0

    @property
    def conformity(self) -> float:
        rejected = sum(count for _, count in self.rejected)
        counted = self.total - self.null_count
        return 1.0 if counted <= 0 else max(0.0, 1.0 - rejected / counted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": pw.to_json(self.pw_type),
            "type_name": str(self.pw_type),
            "finding": self.finding.to_dict(),
            "null_tokens": list(self.null_tokens),
            "rejected": [{"value": value, "count": count} for value, count in self.rejected],
            "date_format": self.date_format,
            "number_format": self.number_format,
            "excel_errors": self.excel_errors,
            "null_count": self.null_count,
            "total": self.total,
            "conformity": round(self.conformity, 4),
        }


def _is_null(value: str, tokens: set[str]) -> bool:
    return value.strip().lower() in tokens


def detect_null_tokens(values: Iterable[str]) -> list[str]:
    """Which of the conventional "no value" strings this column actually uses.

    Reported rather than applied blindly: a column where `NA` means North
    America is not hypothetical, and naming the tokens is what lets somebody
    say so.
    """
    seen = {str(value).strip().lower() for value in values}
    return [token for token in NULL_TOKENS if token and token in seen]


def profile_column(
    name: str, values: Iterable[Any], *, sample: int = 10_000
) -> ColumnProfile:
    """Decide one column's type from its values."""
    raw = [value for value in values][:sample]
    text = [str(value) for value in raw if value is not None]
    tokens = set(detect_null_tokens(text)) | {""}
    non_null = [value for value in text if not _is_null(value, tokens)]
    errors = sum(1 for value in non_null if value.strip().upper() in EXCEL_ERRORS)
    non_null = [value for value in non_null if value.strip().upper() not in EXCEL_ERRORS]

    profile = ColumnProfile(
        name=name,
        pw_type=pw.STRING,
        finding=Finding(
            stage="column_type",
            value="string",
            certainty=Certainty.LIKELY,
            confidence=1.0,
            reason="Free text.",
        ),
        null_tokens=sorted(tokens - {""}),
        excel_errors=errors,
        null_count=len(text) - len(non_null) - errors,
        total=len(text),
    )

    if not non_null:
        profile.finding = Finding(
            stage="column_type",
            value="string",
            certainty=Certainty.UNCERTAIN,
            confidence=0.0,
            reason="Every value is empty or a null token, so there is nothing to type.",
            evidence=sorted(tokens - {""})[:5],
        )
        return profile

    lowered = [value.strip().lower() for value in non_null]

    # --- boolean ---------------------------------------------------------
    if set(lowered) <= set(TRUE_TOKENS) | set(FALSE_TOKENS):
        # A column of only 0 and 1 is as likely to be a flag as a count, and
        # calling it boolean loses arithmetic. Integers win that tie.
        if not set(lowered) <= {"0", "1"}:
            profile.pw_type = pw.BOOLEAN
            profile.finding = Finding(
                stage="column_type",
                value="boolean",
                certainty=Certainty.LIKELY,
                confidence=1.0,
                reason=f"Every value is one of {sorted(set(lowered))}.",
                evidence=sorted(set(non_null))[:4],
            )
            return profile

    # --- dates -----------------------------------------------------------
    dateish = [value for value in non_null if dates.looks_like_date(value)]
    if dateish and len(dateish) / len(non_null) >= 0.8:
        result = dates.detect(non_null, column=name)
        profile.date_format = result.fmt
        profile.finding = result.finding
        profile.rejected = _tally(result.rejected)
        profile.pw_type = (
            pw.DATE if result.fmt and "%H" not in result.fmt else pw.timestamp()
        ) if result.fmt else pw.STRING
        return profile

    # --- identifiers that look numeric -----------------------------------
    # `01234` is a postcode, an account number or a SKU. Read as a number it
    # becomes 1234 and the leading zero is gone for good -- and unlike most
    # inference mistakes this one is invisible, because 1234 is a perfectly
    # plausible value for the column to hold.
    padded = [value for value in non_null if _has_leading_zero(value)]
    if padded:
        widths = {len(value.strip()) for value in non_null}
        profile.pw_type = pw.string(max(widths))
        profile.finding = Finding(
            stage="column_type",
            value="string",
            certainty=Certainty.LIKELY,
            confidence=0.95,
            reason=(
                f"{len(padded)} value(s) have a leading zero, so this is an identifier "
                "rather than a number. Reading it as a number would turn "
                f"{padded[0]!r} into {padded[0].lstrip('0') or '0'}."
                + (
                    " Every value is the same width, which is what a fixed-length code "
                    "looks like."
                    if len(widths) == 1
                    else ""
                )
            ),
            candidates=[Candidate("number", 0.3, "the values are digits")],
            evidence=padded[:4],
        )
        return profile

    # --- numbers ---------------------------------------------------------
    numericish = [value for value in non_null if numbers.looks_numeric(value)]
    if numericish and len(numericish) / len(non_null) >= 0.8:
        fmt = numbers.detect(non_null, column=name)
        parsed: list[float] = []
        rejected: list[str] = []
        for value in non_null:
            number = fmt.parse(value)
            if number is None:
                rejected.append(value)
            else:
                parsed.append(number)

        profile.number_format = fmt.to_dict()
        profile.rejected = _tally(rejected)

        if fmt.finding.certainty is Certainty.AMBIGUOUS:
            # The separator is unresolved, so the type is too: reading it either
            # way produces a number, and they differ by a factor of a thousand.
            profile.pw_type = pw.STRING
            profile.finding = fmt.finding
            return profile

        # A value *written* with a decimal point is a decimal, even when it
        # happens to be a round number. `10.00` in a price column is not the
        # integer 10: narrowing it drops the cents, and an export then stores
        # an integer where the source had a float. The text decides, not the
        # arithmetic.
        written_decimal = any(
            fmt.decimal in numbers.strip_decoration(value)[0] for value in non_null
        )
        whole = (
            bool(parsed)
            and not written_decimal
            and all(float(value).is_integer() for value in parsed)
        )
        profile.pw_type = _integer_type(parsed) if whole else pw.FLOAT64
        profile.finding = Finding(
            stage="column_type",
            value=str(profile.pw_type),
            certainty=Certainty.LIKELY if not rejected else Certainty.UNCERTAIN,
            confidence=len(parsed) / max(len(non_null), 1),
            reason=(
                f"{len(parsed)}/{len(non_null)} values read as "
                f"{'whole numbers' if whole else 'decimals'}"
                + (f"; {len(rejected)} did not" if rejected else "")
                + f". {fmt.finding.reason}"
            ),
            evidence=non_null[:3] + ([f"rejected: {value}" for value in rejected[:3]]),
        )
        return profile

    # --- free text -------------------------------------------------------
    widths = [len(value) for value in non_null]
    distinct = len(set(non_null))
    profile.pw_type = pw.string(max(widths) if widths else None)
    profile.finding = Finding(
        stage="column_type",
        value="string",
        certainty=Certainty.LIKELY,
        confidence=1.0,
        reason=(
            f"Text, {min(widths)}–{max(widths)} characters, {distinct} distinct value(s)"
            + (
                f". {len(numericish)} value(s) look numeric but not enough to call the "
                "column numeric"
                if numericish
                else ""
            )
            + "."
        ),
        candidates=(
            [Candidate("number", len(numericish) / len(non_null), "some values are numeric")]
            if numericish
            else []
        ),
        evidence=non_null[:4],
    )
    return profile


def _has_leading_zero(value: str) -> bool:
    """`01234` yes; `0` no; `0.5` no; `-012` yes."""
    text = value.strip().lstrip("+-")
    if len(text) < 2 or not text.isdigit():
        return False
    return text[0] == "0"


def _tally(values: list[str]) -> list[tuple[str, int]]:
    """The values that did not fit, commonest first.

    Counted rather than listed: eight hundred rows saying `N/A` is one problem,
    and eight hundred distinct malformed values is a different one.
    """
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:MAX_REJECTED]


def _integer_type(values: list[float]) -> PWType:
    """The narrowest integer type that holds every value.

    Narrowest rather than always BIGINT: the width travels into the warehouse
    DDL, and a table of `bigint` columns holding values under a thousand is a
    cost somebody pays for every row.
    """
    if not values:
        return pw.INT32
    smallest, largest = min(values), max(values)
    for candidate, low, high in (
        (pw.INT16, -32_768, 32_767),
        (pw.INT32, -2_147_483_648, 2_147_483_647),
    ):
        if low <= smallest and largest <= high:
            return candidate
    return pw.INT64
