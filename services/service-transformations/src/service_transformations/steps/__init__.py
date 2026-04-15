"""Transformation step implementations (preview and future execution)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from service_transformations.steps.cast_column_types import apply_cast_column_types
from service_transformations.steps.drop_columns import apply_drop_columns
from service_transformations.steps.drop_null_rows import apply_drop_null_rows
from service_transformations.steps.fill_nulls import apply_fill_nulls
from service_transformations.steps.filter_rows import apply_filter_rows
from service_transformations.steps.parse_dates import apply_parse_dates
from service_transformations.steps.remove_duplicates import apply_remove_duplicates
from service_transformations.steps.rename_columns import apply_rename_columns
from service_transformations.steps.select_columns import apply_select_columns
from service_transformations.steps.trim_strings import apply_trim_strings

StepApplyFn = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.DataFrame, list[str]]]

STEP_APPLY_FUNCTIONS: dict[str, StepApplyFn] = {
    "rename_columns": apply_rename_columns,
    "cast_column_types": apply_cast_column_types,
    "trim_strings": apply_trim_strings,
    "drop_columns": apply_drop_columns,
    "select_columns": apply_select_columns,
    "fill_nulls": apply_fill_nulls,
    "drop_null_rows": apply_drop_null_rows,
    "remove_duplicates": apply_remove_duplicates,
    "filter_rows": apply_filter_rows,
    "parse_dates": apply_parse_dates,
}

__all__ = [
    "STEP_APPLY_FUNCTIONS",
    "StepApplyFn",
    "apply_cast_column_types",
    "apply_drop_columns",
    "apply_drop_null_rows",
    "apply_fill_nulls",
    "apply_filter_rows",
    "apply_parse_dates",
    "apply_remove_duplicates",
    "apply_rename_columns",
    "apply_select_columns",
    "apply_trim_strings",
]
