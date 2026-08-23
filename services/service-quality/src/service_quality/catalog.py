"""Machine-readable descriptions of each rule type.

The UI builds its rule editor from this, so adding a rule type surfaces in the
product without a matching frontend change.
"""

from __future__ import annotations

from service_quality.rules.base import DATASET_LEVEL_RULES
from service_quality.schemas import RuleCatalogResponse, RuleTypeInfo

_CATALOG: tuple[tuple[str, str, list[str], list[str]], ...] = (
    (
        "not_null",
        "Every row must have a value in the column.",
        ["column"],
        [],
    ),
    (
        "unique",
        "Values in the column (or combination of columns) must not repeat.",
        ["column"],
        ["columns"],
    ),
    (
        "allowed_values",
        "Values must come from a fixed set.",
        ["column", "allowed_values"],
        ["allow_null"],
    ),
    (
        "range",
        "Numeric values must fall between a minimum and maximum.",
        ["column"],
        ["min", "max"],
    ),
    (
        "regex_match",
        "Text values must match a regular expression in full.",
        ["column", "pattern"],
        ["allow_null"],
    ),
    (
        "expression",
        "A custom expression must be true for every row, e.g. total >= 0.",
        ["expression"],
        [],
    ),
    (
        "row_count",
        "The dataset must contain a row count within the expected bounds.",
        [],
        ["min", "max"],
    ),
    (
        "freshness",
        "The newest timestamp must be within the allowed age.",
        ["column", "max_age_hours"],
        [],
    ),
)


def rule_catalog() -> RuleCatalogResponse:
    return RuleCatalogResponse(
        items=[
            RuleTypeInfo(
                rule_type=rule_type,
                description=description,
                required_config=required,
                optional_config=optional,
                row_level=rule_type not in DATASET_LEVEL_RULES,
            )
            for rule_type, description, required, optional in _CATALOG
        ]
    )
