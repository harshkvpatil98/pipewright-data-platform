"""The built-in data quality rule implementations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Callable

import pandas as pd

from service_quality.rules.base import RuleEvaluation, from_mask, passed
from service_transformations.expressions import evaluate_expression
from shared_python.errors import BadRequestError

MAX_REGEX_LENGTH = 500


def _require_column(dataframe: pd.DataFrame, config: dict[str, Any]) -> str:
    column = config.get("column")
    if not isinstance(column, str) or not column.strip():
        raise BadRequestError("This rule requires config.column.")
    column = column.strip()
    if column not in dataframe.columns:
        raise BadRequestError(f"Column '{column}' is not present in the dataset.")
    return column


def _require_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    columns = config.get("columns")
    if not isinstance(columns, list) or not columns:
        raise BadRequestError("This rule requires a non-empty config.columns list.")
    resolved: list[str] = []
    for entry in columns:
        if not isinstance(entry, str) or not entry.strip():
            raise BadRequestError("config.columns must contain only non-empty strings.")
        name = entry.strip()
        if name not in dataframe.columns:
            raise BadRequestError(f"Column '{name}' is not present in the dataset.")
        resolved.append(name)
    return resolved


def evaluate_not_null(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    column = _require_column(dataframe, config)
    mask = dataframe[column].isna()
    return from_mask(
        mask,
        message_when_failed=f"{{failed}} of {{total}} row(s) have a null '{column}'.",
        message_when_passed=f"All {{total}} row(s) have a value for '{column}'.",
        column=column,
    )


def evaluate_unique(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    columns = _require_columns(dataframe, config) if config.get("columns") else [_require_column(dataframe, config)]
    # Every member of a duplicated group is flagged, so quarantine removes the
    # whole collision rather than arbitrarily keeping one row.
    mask = dataframe.duplicated(subset=columns, keep=False)
    label = ", ".join(columns)
    return from_mask(
        mask,
        message_when_failed=f"{{failed}} of {{total}} row(s) share a duplicate value for ({label}).",
        message_when_passed=f"All {{total}} row(s) are unique on ({label}).",
        columns=columns,
    )


def evaluate_allowed_values(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    column = _require_column(dataframe, config)
    allowed = config.get("allowed_values")
    if not isinstance(allowed, list) or not allowed:
        raise BadRequestError("config.allowed_values must be a non-empty list.")

    series = dataframe[column]
    allow_null = bool(config.get("allow_null", True))
    comparable = {str(value) for value in allowed}
    as_text = series.astype("string")

    mask = ~as_text.isin(comparable)
    if allow_null:
        mask &= series.notna()
    else:
        mask |= series.isna()

    observed = sorted({str(value) for value in series.dropna().unique() if str(value) not in comparable})[:20]
    return from_mask(
        mask,
        message_when_failed=f"{{failed}} of {{total}} row(s) have a value outside the allowed set for '{column}'.",
        message_when_passed=f"All {{total}} row(s) use allowed values for '{column}'.",
        column=column,
        unexpected_values=observed,
    )


def evaluate_range(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    column = _require_column(dataframe, config)
    minimum, maximum = config.get("min"), config.get("max")
    if minimum is None and maximum is None:
        raise BadRequestError("A range rule requires config.min, config.max, or both.")
    for label, bound in (("min", minimum), ("max", maximum)):
        if bound is not None and not isinstance(bound, (int, float)) or isinstance(bound, bool):
            raise BadRequestError(f"config.{label} must be a number.")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise BadRequestError("config.min cannot be greater than config.max.")

    numeric = pd.to_numeric(dataframe[column], errors="coerce")
    # Non-numeric text in a numeric range check is itself a failure, not a skip.
    mask = numeric.isna() & dataframe[column].notna()
    if minimum is not None:
        mask |= numeric < minimum
    if maximum is not None:
        mask |= numeric > maximum
    mask = mask.fillna(False)

    return from_mask(
        mask,
        message_when_failed=f"{{failed}} of {{total}} row(s) fall outside the allowed range for '{column}'.",
        message_when_passed=f"All {{total}} row(s) are within range for '{column}'.",
        column=column,
        min=minimum,
        max=maximum,
    )


def evaluate_regex_match(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    column = _require_column(dataframe, config)
    pattern = config.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise BadRequestError("config.pattern must be a non-empty string.")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise BadRequestError(f"config.pattern exceeds {MAX_REGEX_LENGTH} characters.")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise BadRequestError(f"config.pattern is not a valid regular expression: {exc}.") from exc

    series = dataframe[column]
    allow_null = bool(config.get("allow_null", True))
    matches = series.astype("string").str.fullmatch(pattern).fillna(False)

    mask = ~matches
    if allow_null:
        mask &= series.notna()

    return from_mask(
        mask,
        message_when_failed=f"{{failed}} of {{total}} row(s) do not match the required pattern for '{column}'.",
        message_when_passed=f"All {{total}} row(s) match the pattern for '{column}'.",
        column=column,
        pattern=pattern,
    )


def evaluate_expression_rule(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    """Pass when the operator's expression is true for every row.

    Reuses the transformation expression evaluator, so the same safe, vectorised
    syntax works for both derived columns and quality assertions.
    """
    expression = config.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise BadRequestError("config.expression must be a non-empty string.")

    result, _ = evaluate_expression(dataframe, expression)
    truthy = result.fillna(False).astype(bool)
    mask = ~truthy

    return from_mask(
        mask,
        message_when_failed="{failed} of {total} row(s) fail the expression assertion.",
        message_when_passed="All {total} row(s) satisfy the expression assertion.",
        expression=expression,
    )


def evaluate_row_count(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    minimum, maximum = config.get("min"), config.get("max")
    if minimum is None and maximum is None:
        raise BadRequestError("A row_count rule requires config.min, config.max, or both.")

    total = int(len(dataframe))
    problems: list[str] = []
    if minimum is not None and total < int(minimum):
        problems.append(f"expected at least {int(minimum)}")
    if maximum is not None and total > int(maximum):
        problems.append(f"expected at most {int(maximum)}")

    if problems:
        return RuleEvaluation(
            status="failed",
            evaluated_rows=total,
            failed_rows=total,
            message=f"Dataset has {total} row(s) but {' and '.join(problems)}.",
            details={"row_count": total, "min": minimum, "max": maximum},
        )
    return passed(total, f"Dataset row count ({total}) is within the expected range.", row_count=total)


def evaluate_freshness(dataframe: pd.DataFrame, config: dict[str, Any]) -> RuleEvaluation:
    """Fail when the newest timestamp is older than the allowed age."""
    column = _require_column(dataframe, config)
    max_age_hours = config.get("max_age_hours")
    if not isinstance(max_age_hours, (int, float)) or isinstance(max_age_hours, bool) or max_age_hours <= 0:
        raise BadRequestError("config.max_age_hours must be a positive number.")

    parsed = pd.to_datetime(dataframe[column], errors="coerce", utc=True)
    newest = parsed.max()
    total = int(len(dataframe))

    if pd.isna(newest):
        return RuleEvaluation(
            status="failed",
            evaluated_rows=total,
            failed_rows=total,
            message=f"Column '{column}' has no parseable timestamps, so freshness cannot be confirmed.",
            details={"column": column},
        )

    age_hours = (datetime.now(UTC) - newest.to_pydatetime()).total_seconds() / 3600.0
    details = {
        "column": column,
        "newest_value": newest.isoformat(),
        "age_hours": round(age_hours, 2),
        "max_age_hours": max_age_hours,
    }

    if age_hours > max_age_hours:
        return RuleEvaluation(
            status="failed",
            evaluated_rows=total,
            failed_rows=total,
            message=(
                f"Newest '{column}' is {age_hours:.1f}h old, exceeding the {max_age_hours}h freshness limit."
            ),
            details=details,
        )
    return passed(total, f"Data is fresh: newest '{column}' is {age_hours:.1f}h old.", **details)


RuleEvaluator = Callable[[pd.DataFrame, dict[str, Any]], RuleEvaluation]

RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "not_null": evaluate_not_null,
    "unique": evaluate_unique,
    "allowed_values": evaluate_allowed_values,
    "range": evaluate_range,
    "regex_match": evaluate_regex_match,
    "expression": evaluate_expression_rule,
    "row_count": evaluate_row_count,
    "freshness": evaluate_freshness,
}

SUPPORTED_RULE_TYPES: tuple[str, ...] = tuple(sorted(RULE_EVALUATORS))
