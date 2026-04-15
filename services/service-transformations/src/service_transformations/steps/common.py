from __future__ import annotations

import re
from typing import Any

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from shared_python.errors import BadRequestError

ALLOWED_CAST_TARGET_TYPES = frozenset({"string", "int", "float", "datetime", "boolean"})
ALLOWED_FILL_NULL_STRATEGIES = frozenset({"constant", "mean", "median", "mode"})
ALLOWED_NULL_DROP_HOW = frozenset({"any", "all"})
ALLOWED_DUPLICATE_KEEP = frozenset({"first", "last", "none"})
ALLOWED_FILTER_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "contains",
        "in",
    }
)
ALLOWED_PARSE_DATE_ERRORS = frozenset({"coerce", "raise", "ignore"})


def ensure_config_keys(
    config: Any, *, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise BadRequestError("config must be an object.")

    optional = optional or set()
    missing_keys = sorted(required - set(config.keys()))
    if missing_keys:
        raise BadRequestError(f"config is missing required field(s): {', '.join(missing_keys)}.")

    extra_keys = sorted(set(config.keys()) - required - optional)
    if extra_keys:
        raise BadRequestError(f"config contains unsupported field(s): {', '.join(extra_keys)}.")

    return config


def ensure_columns_exist(dataframe: pd.DataFrame, columns: list[str], *, field_name: str) -> None:
    missing = [column for column in columns if column not in dataframe.columns]
    if missing:
        raise BadRequestError(f"{field_name} contains unknown column(s): {', '.join(missing)}.")


def require_string_list(value: Any, *, field_name: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise BadRequestError(f"{field_name} must be a list.")
    if not allow_empty and not value:
        raise BadRequestError(f"{field_name} cannot be empty.")

    normalized: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise BadRequestError(f"{field_name}[{index}] must be a non-empty string.")
        normalized.append(item.strip())
    return normalized


def require_mapping(value: Any, *, field_name: str, allow_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BadRequestError(f"{field_name} must be an object.")
    if not allow_empty and not value:
        raise BadRequestError(f"{field_name} cannot be empty.")
    return value


def infer_series_type(series: pd.Series) -> str:
    from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype, is_string_dtype

    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    if is_bool_dtype(series):
        return "boolean"
    if is_integer_dtype(series):
        return "int"
    if is_numeric_dtype(series):
        return "float"
    if is_datetime64_any_dtype(series):
        return "datetime"
    if is_string_dtype(series):
        return "string"

    python_types = {type(value).__name__ for value in non_null.tolist()}
    if python_types <= {"str"}:
        return "string"
    if python_types <= {"bool"}:
        return "boolean"
    if python_types <= {"int"}:
        return "int"
    if python_types <= {"int", "float"}:
        return "float"
    if python_types <= {"Timestamp", "datetime"}:
        return "datetime"
    return "mixed" if len(python_types) > 1 else python_types.pop().lower()


def is_numeric_series(series: pd.Series) -> bool:
    return infer_series_type(series) in {"int", "float"}


def is_ordering_compatible_series(series: pd.Series) -> bool:
    return infer_series_type(series) in {"int", "float", "datetime"} or is_datetime64_any_dtype(series)


def is_string_compatible_for_contains(series: pd.Series) -> bool:
    t = infer_series_type(series)
    if t in {"string", "empty"}:
        return True
    if t == "mixed":
        non_null = series.dropna()
        return bool(non_null.empty or all(isinstance(value, str) for value in non_null.tolist()))
    return False


def count_introduced_nulls(before: pd.Series, after: pd.Series) -> int:
    return int((before.notna() & after.isna()).sum())


def regex_contains(series: pd.Series, needle: str) -> pd.Series:
    pattern = re.escape(needle)

    def cell_match(value: object) -> bool:
        if pd.isna(value):
            return False
        return re.search(pattern, str(value)) is not None

    return series.map(cell_match)
