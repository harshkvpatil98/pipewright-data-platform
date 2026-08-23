"""Turning what a profile already noticed into rules worth asserting.

Every fact needed to write a good quality rule is already in the profile: this
column has never been null, that one only ever holds four values, this one is
unique on every row. Nobody writes the rules because writing thirty of them is
an afternoon.

The bar for suggesting one is deliberately high. A rule that fires spuriously is
worse than no rule -- it gets muted, and the muting takes the real failures with
it -- so a suggestion is only made where the profile shows a pattern strong
enough that a violation would genuinely be news.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A column that has never been null in a decent number of rows is worth
# asserting on. Fewer rows than this and "never null" is not yet a pattern.
MIN_ROWS_FOR_NOT_NULL = 50

# A column with few enough distinct values is a category, and a new value
# appearing is worth knowing about.
MAX_CATEGORY_VALUES = 12
MIN_ROWS_FOR_CATEGORY = 100

# Uniqueness needs enough rows to be a pattern rather than a coincidence. In
# eight rows every amount is distinct and that means nothing; a rule asserting
# it would fail on the ninth row and teach people to ignore rule failures.
MIN_ROWS_FOR_UNIQUE = 200


@dataclass
class RuleSuggestion:
    name: str
    rule_type: str
    severity: str
    config: dict[str, Any]
    rationale: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "config": self.config,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


def suggest_rules(profile: dict[str, Any] | None) -> list[RuleSuggestion]:
    """Rules the profile already justifies."""
    if not isinstance(profile, dict):
        return []

    row_count = int(profile.get("row_count") or 0)
    columns = profile.get("columns")
    if not isinstance(columns, list) or row_count == 0:
        return []

    suggestions: list[RuleSuggestion] = []

    if not profile.get("duplicate_row_count"):
        suggestions.append(
            RuleSuggestion(
                name="No duplicate rows",
                rule_type="row_count",
                severity="warning",
                config={"min": 1},
                rationale=(
                    f"All {row_count:,} rows are distinct today. A rule keeps that true."
                ),
                confidence="medium",
            )
        )

    for entry in columns:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue

        suggestions.extend(_column_rules(name, entry, row_count))

    return suggestions


def _column_rules(name: str, entry: dict[str, Any], row_count: int) -> list[RuleSuggestion]:
    suggestions: list[RuleSuggestion] = []
    null_count = int(entry.get("null_count") or 0)
    unique_count = int(entry.get("unique_count") or 0)
    inferred = str(entry.get("inferred_type") or "")

    if null_count == 0 and row_count >= MIN_ROWS_FOR_NOT_NULL:
        suggestions.append(
            RuleSuggestion(
                name=f"{name} is always present",
                rule_type="not_null",
                severity="error",
                config={"column": name},
                rationale=(
                    f"'{name}' has a value in all {row_count:,} rows. A missing one "
                    "would be a change worth stopping for."
                ),
                confidence="high",
            )
        )

    if entry.get("possible_identifier") and row_count >= MIN_ROWS_FOR_UNIQUE:
        suggestions.append(
            RuleSuggestion(
                name=f"{name} is unique",
                rule_type="unique",
                severity="error",
                config={"column": name},
                rationale=(
                    f"All {row_count:,} rows have a different '{name}', so it is being "
                    "used as an identifier. Duplicates would break anything joining on it."
                ),
                confidence="high",
            )
        )

    if (
        inferred == "string"
        and 1 < unique_count <= MAX_CATEGORY_VALUES
        and row_count >= MIN_ROWS_FOR_CATEGORY
    ):
        samples = entry.get("sample_values")
        if isinstance(samples, list) and samples:
            allowed = sorted({str(value) for value in samples if value is not None})
            suggestions.append(
                RuleSuggestion(
                    name=f"{name} is one of {len(allowed)} known values",
                    rule_type="allowed_values",
                    severity="warning",
                    config={"column": name, "allowed_values": allowed, "allow_null": null_count > 0},
                    rationale=(
                        f"'{name}' only ever holds {unique_count} distinct values across "
                        f"{row_count:,} rows, so a new one appearing is worth knowing about."
                    ),
                    # Medium, not high: the sample may not have seen every
                    # legitimate value, and this rule fires when it has not.
                    confidence="medium",
                )
            )

    minimum, maximum = entry.get("min_value"), entry.get("max_value")
    if (
        inferred in ("int", "float")
        and isinstance(minimum, (int, float))
        and isinstance(maximum, (int, float))
        and minimum >= 0
        and maximum > minimum
    ):
        suggestions.append(
            RuleSuggestion(
                name=f"{name} stays non-negative",
                rule_type="range",
                severity="error",
                config={"column": name, "min": 0},
                rationale=(
                    f"'{name}' runs from {minimum:g} to {maximum:g} and has never been "
                    "negative. A negative value would usually mean a sign error upstream."
                ),
                confidence="high",
            )
        )

    return suggestions


def summarise(suggestions: list[RuleSuggestion]) -> str:
    if not suggestions:
        return (
            "Nothing in this profile is a strong enough pattern to assert on yet. "
            "More rows, or more consistent ones, would give something to work with."
        )
    high = sum(1 for item in suggestions if item.confidence == "high")
    return (
        f"{len(suggestions)} rule(s) the profile already justifies, {high} of them "
        "on patterns strong enough that a violation would be news."
    )
