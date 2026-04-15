from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_FILTER_OPERATORS,
    ensure_columns_exist,
    ensure_config_keys,
    infer_series_type,
    is_ordering_compatible_series,
    is_string_compatible_for_contains,
    regex_contains,
)


def validate_filter_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    config = ensure_config_keys(config, required={"conditions"})
    conditions = config["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise BadRequestError("config.conditions must be a non-empty list.")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(conditions, start=1):
        prefix = f"config.conditions[{index}]"
        if not isinstance(raw, dict):
            raise BadRequestError(f"{prefix} must be an object.")
        for key in ("column", "operator", "value"):
            if key not in raw:
                raise BadRequestError(f"{prefix} is missing required field '{key}'.")
        extra = set(raw.keys()) - {"column", "operator", "value"}
        if extra:
            raise BadRequestError(f"{prefix} contains unsupported field(s): {', '.join(sorted(extra))}.")

        column = raw["column"]
        operator = raw["operator"]
        value = raw["value"]

        if not isinstance(column, str) or not column.strip():
            raise BadRequestError(f"{prefix}.column must be a non-empty string.")
        column = column.strip()

        if not isinstance(operator, str) or operator not in ALLOWED_FILTER_OPERATORS:
            allowed = ", ".join(sorted(ALLOWED_FILTER_OPERATORS))
            raise BadRequestError(f"{prefix}.operator must be one of: {allowed}.")

        ensure_columns_exist(dataframe, [column], field_name=f"{prefix}.column")

        series = dataframe[column]
        if operator == "in":
            if not isinstance(value, list):
                raise BadRequestError(f'{prefix}.value must be a list when operator is "in".')
        elif operator == "contains":
            if not is_string_compatible_for_contains(series):
                raise BadRequestError(
                    f'{prefix}: "contains" is only supported for string-compatible columns.'
                )
        elif operator in {
            "greater_than",
            "greater_or_equal",
            "less_than",
            "less_or_equal",
        }:
            if not is_ordering_compatible_series(series):
                raise BadRequestError(
                    f'{prefix}: ordering operators require numeric or datetime columns.'
                )

        normalized.append({"column": column, "operator": operator, "value": value})

    return normalized


def apply_filter_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    conditions = validate_filter_rows(dataframe, config)
    mask = pd.Series(True, index=dataframe.index)

    for cond in conditions:
        column = cond["column"]
        operator = cond["operator"]
        value = cond["value"]
        series = dataframe[column]
        stype = infer_series_type(series)

        if operator == "equals":
            mask &= series.eq(value)
        elif operator == "not_equals":
            mask &= ~series.eq(value)
        elif operator == "in":
            mask &= series.isin(value)
        elif operator == "contains":
            mask &= regex_contains(series, str(value))
        elif operator == "greater_than":
            mask &= _compare_ordering(series, stype, value, lambda a, b: a > b)
        elif operator == "greater_or_equal":
            mask &= _compare_ordering(series, stype, value, lambda a, b: a >= b)
        elif operator == "less_than":
            mask &= _compare_ordering(series, stype, value, lambda a, b: a < b)
        elif operator == "less_or_equal":
            mask &= _compare_ordering(series, stype, value, lambda a, b: a <= b)
        else:
            raise BadRequestError(f'Unsupported operator "{operator}".')

    return dataframe.loc[mask].copy(), []


def _compare_ordering(
    series: pd.Series, stype: str, value: Any, comparator: Any
) -> pd.Series:
    if stype == "datetime" or pd.api.types.is_datetime64_any_dtype(series):
        left = pd.to_datetime(series, errors="coerce")
        right = pd.to_datetime(value, errors="coerce")
        if pd.isna(right):
            raise BadRequestError("Filter value could not be parsed as a datetime.")
        return comparator(left, right)

    left = pd.to_numeric(series, errors="coerce")
    if isinstance(value, bool):
        raise BadRequestError("Numeric filter value cannot be a boolean.")
    right = pd.to_numeric(value, errors="coerce")
    if pd.isna(right) and not isinstance(value, (int, float)):
        raise BadRequestError("Filter value must be numeric for ordering comparisons.")
    return comparator(left, right)
