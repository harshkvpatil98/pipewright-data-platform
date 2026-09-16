"""`1.234,56` or `1,234.56`?

Decided **per column**, not per file, because a single export routinely mixes
them: an amount written by a German accounting system next to a quantity
written by a US one. Deciding per file gets one of the two columns wrong and
there is no error to notice.

The reasoning, in order:

* **Both separators present.** Whichever comes last is the decimal point.
  `1.234,56` ends `,56`; `1,234.56` ends `.56`. Certain — no other reading fits.
* **One separator, groups of three.** `1.234` and `12.345.678` are thousands
  separators: a decimal fraction of exactly three digits, repeatedly, is not
  how people write money.
* **One separator, not three digits after.** `1.5` and `12,75` are decimals.
* **Ambiguous.** `1.234` on its own genuinely could be either — one thousand
  two hundred and thirty-four, or one point two three four. When a column
  contains only such values, this says so rather than picking.

Currency symbols, percent signs, spaces used as thousands separators and
parenthesised negatives (`(1,234.56)` is how accounting writes -1234.56) are
all handled, because they are what is actually in the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from service_ingestion.sniff.evidence import Candidate, Certainty, Finding, certain

#: Symbols stripped before a value is read as a number.
CURRENCY = "$€£¥₹₽¢₩₪R "

#: A number once the decorations are gone.
_NUMERIC = re.compile(r"^[+-]?[\d.,'\s]*\d[\d.,'\s]*$")
#: Exactly three digits after the final separator: a thousands group.
_TRAILING_GROUP = re.compile(r"[.,'\s](\d{3})$")
#: Anything but three digits after the final separator: a decimal fraction.
_TRAILING_FRACTION = re.compile(r"[.,](\d{1,2}|\d{4,})$")


@dataclass
class NumberFormat:
    decimal: str
    thousands: str | None
    #: True when negatives are written `(123)` rather than `-123`.
    accounting_negatives: bool
    finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {
            "decimal": self.decimal,
            "thousands": self.thousands,
            "accounting_negatives": self.accounting_negatives,
            "finding": self.finding.to_dict(),
        }

    def parse(self, value: str) -> float | None:
        """One value as a number, under this column's convention."""
        return parse_number(value, decimal=self.decimal, thousands=self.thousands)


def strip_decoration(value: str) -> tuple[str, bool]:
    """A bare number, and whether it was written as an accounting negative."""
    text = str(value).strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    for symbol in CURRENCY:
        text = text.replace(symbol, "")
    text = text.replace("%", "").strip()
    if text.endswith("-"):  # trailing-minus, as SAP writes it
        negative = True
        text = text[:-1].strip()
    return text, negative


def parse_number(value: str, *, decimal: str, thousands: str | None) -> float | None:
    """Read one value, or None when it is not a number under this convention."""
    text, negative = strip_decoration(value)
    if not text:
        return None
    sign = -1.0 if negative else 1.0
    if text.startswith("-"):
        sign = -sign
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]

    if thousands:
        text = text.replace(thousands, "")
    # A space is a thousands separator in French and Scandinavian conventions,
    # and never anything else inside a number.
    text = text.replace(" ", "").replace(" ", "")
    if decimal != ".":
        text = text.replace(decimal, ".")
    if not text or text.count(".") > 1:
        return None
    try:
        return sign * float(text)
    except ValueError:
        return None


def looks_numeric(value: str) -> bool:
    text, _ = strip_decoration(value)
    return bool(text) and bool(_NUMERIC.match(text))


def detect(values: Iterable[str], *, column: str = "") -> NumberFormat:
    """The decimal and thousands convention of one column."""
    sample: list[str] = []
    accounting = False
    for raw in values:
        text, negative = strip_decoration(str(raw))
        if not text:
            continue
        accounting = accounting or negative
        if _NUMERIC.match(text):
            sample.append(text)

    if not sample:
        return NumberFormat(
            decimal=".",
            thousands=None,
            accounting_negatives=accounting,
            finding=certain(
                "number_format", ".", "No numeric values in this column; the default applies."
            ),
        )

    both = [item for item in sample if "." in item and "," in item]
    if both:
        # Whichever comes last is the decimal point. Nothing else is consistent
        # with a number having one fractional part.
        last_is_comma = sum(1 for item in both if item.rfind(",") > item.rfind("."))
        decimal = "," if last_is_comma > len(both) / 2 else "."
        thousands = "." if decimal == "," else ","
        return NumberFormat(
            decimal=decimal,
            thousands=thousands,
            accounting_negatives=accounting,
            finding=certain(
                "number_format",
                decimal,
                (
                    f"Values contain both separators, e.g. '{both[0]}'. The last one is "
                    f"the decimal point, so '{decimal}' is decimal and '{thousands}' groups."
                ),
                evidence=both[:4],
            ),
        )

    grouped = sum(1 for item in sample if _TRAILING_GROUP.search(item))
    fractional = sum(1 for item in sample if _TRAILING_FRACTION.search(item))
    separators = {character for item in sample for character in item if character in ".,'"}

    if not separators:
        return NumberFormat(
            decimal=".",
            thousands=None,
            accounting_negatives=accounting,
            finding=certain(
                "number_format", ".", "Whole numbers with no separators.", evidence=sample[:3]
            ),
        )

    separator = next(iter(separators)) if len(separators) == 1 else "."

    if fractional and not grouped:
        return NumberFormat(
            decimal=separator,
            thousands=None,
            accounting_negatives=accounting,
            finding=certain(
                "number_format",
                separator,
                f"'{separator}' is followed by a fractional part, e.g. '{sample[0]}'.",
                evidence=sample[:4],
            ),
        )

    if grouped and not fractional:
        other = "," if separator == "." else "."
        ambiguous = [item for item in sample if _TRAILING_GROUP.search(item)]
        # `1.234` alone is genuinely both readings. Only when several values
        # group repeatedly (`12.345.678`) is it settled.
        repeated = any(item.count(separator) > 1 for item in sample)
        if repeated:
            return NumberFormat(
                decimal=other,
                thousands=separator,
                accounting_negatives=accounting,
                finding=certain(
                    "number_format",
                    other,
                    (
                        f"'{separator}' appears more than once in a value, e.g. "
                        f"'{next(i for i in sample if i.count(separator) > 1)}', so it groups "
                        f"thousands and '{other}' is the decimal point."
                    ),
                    evidence=sample[:4],
                ),
            )
        return NumberFormat(
            decimal=other,
            thousands=separator,
            accounting_negatives=accounting,
            finding=Finding(
                stage="number_format",
                value=other,
                certainty=Certainty.AMBIGUOUS,
                confidence=0.5,
                reason=(
                    f"{('Column ' + column + ': ') if column else ''}"
                    f"'{ambiguous[0]}' could be {_spell(ambiguous[0], separator, 'thousands')} "
                    f"or {_spell(ambiguous[0], separator, 'decimal')}. Every separator here is "
                    "followed by exactly three digits, so the file does not say which."
                ),
                candidates=[
                    Candidate(other, 0.5, f"'{separator}' groups thousands"),
                    Candidate(separator, 0.5, f"'{separator}' is the decimal point"),
                ],
                evidence=ambiguous[:5],
                blocking=True,
            ),
        )

    # Mixed: some values group, some are fractional, under one separator. The
    # fractional reading cannot explain the grouped values, so grouping wins.
    other = "," if separator == "." else "."
    return NumberFormat(
        decimal=other if grouped >= fractional else separator,
        thousands=separator if grouped >= fractional else None,
        accounting_negatives=accounting,
        finding=Finding(
            stage="number_format",
            value=other if grouped >= fractional else separator,
            certainty=Certainty.UNCERTAIN,
            confidence=0.6,
            reason=(
                f"'{separator}' is followed by three digits in {grouped} value(s) and by "
                f"a different length in {fractional}. Reading the majority."
            ),
            candidates=[
                Candidate(other, grouped / len(sample), "groups thousands"),
                Candidate(separator, fractional / len(sample), "decimal point"),
            ],
            evidence=sample[:5],
        ),
    )


def _spell(value: str, separator: str, role: str) -> str:
    if role == "thousands":
        return f"{value.replace(separator, '')} (grouped)"
    return f"{value.replace(separator, '.')} (a fraction)"
