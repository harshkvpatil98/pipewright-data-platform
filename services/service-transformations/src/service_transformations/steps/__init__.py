"""Transformation step implementations.

Steps come in two shapes:

* single-frame steps, ``(frame, config) -> (frame, warnings)``, which are pure
  functions of the working frame; and
* multi-input steps, ``(frame, config, context) -> (frame, warnings)``, which
  additionally read another dataset through a :class:`StepContext` resolver.

The executor dispatches on which registry a step type appears in.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from service_transformations.steps.aggregate import apply_aggregate
from service_transformations.steps.cast_column_types import apply_cast_column_types
from service_transformations.steps.context import ContextStepApplyFn, StepContext
from service_transformations.steps.derive_column import apply_derive_column
from service_transformations.steps.drop_columns import apply_drop_columns
from service_transformations.steps.drop_null_rows import apply_drop_null_rows
from service_transformations.steps.fill_nulls import apply_fill_nulls
from service_transformations.steps.filter_rows import apply_filter_rows
from service_transformations.steps.join_datasets import apply_join_datasets
from service_transformations.steps.limit_rows import apply_limit_rows
from service_transformations.steps.parse_dates import apply_parse_dates
from service_transformations.steps.pivot import apply_pivot
from service_transformations.steps.remove_duplicates import apply_remove_duplicates
from service_transformations.steps.rename_columns import apply_rename_columns
from service_transformations.steps.replace_values import apply_replace_values
from service_transformations.steps.select_columns import apply_select_columns
from service_transformations.steps.sort_rows import apply_sort_rows
from service_transformations.steps.split_column import apply_split_column
from service_transformations.steps.trim_strings import apply_trim_strings
from service_transformations.steps.union_datasets import apply_union_datasets
from service_transformations.steps.unpivot import apply_unpivot

StepApplyFn = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.DataFrame, list[str]]]


def _apply_tool(frame: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    # Imported lazily: the tool package imports the IR, which imports this
    # module's siblings, and doing it at module scope closes the loop.
    from service_transformations.tools.apply import apply_tool

    return apply_tool(frame, config)

STEP_APPLY_FUNCTIONS: dict[str, StepApplyFn] = {
    # column shaping
    "rename_columns": apply_rename_columns,
    "cast_column_types": apply_cast_column_types,
    "trim_strings": apply_trim_strings,
    "drop_columns": apply_drop_columns,
    "select_columns": apply_select_columns,
    "split_column": apply_split_column,
    "derive_column": apply_derive_column,
    # value cleaning
    "fill_nulls": apply_fill_nulls,
    "drop_null_rows": apply_drop_null_rows,
    "remove_duplicates": apply_remove_duplicates,
    "replace_values": apply_replace_values,
    "parse_dates": apply_parse_dates,
    # row selection and ordering
    "filter_rows": apply_filter_rows,
    "sort_rows": apply_sort_rows,
    "limit_rows": apply_limit_rows,
    # reshaping
    "aggregate": apply_aggregate,
    "pivot": apply_pivot,
    "unpivot": apply_unpivot,
    # The Phase 16 library. One step type covers every tool in it, because
    # adding a tool must not mean editing the step vocabulary, the validator,
    # the lineage table and the UI catalogue in four places -- which is how a
    # library of hundreds stops being consistent.
    "tool": _apply_tool,
}

# Steps that read a second dataset and therefore need a resolver.
CONTEXT_STEP_APPLY_FUNCTIONS: dict[str, ContextStepApplyFn] = {
    "join_datasets": apply_join_datasets,
    "union_datasets": apply_union_datasets,
}

ALL_STEP_TYPES: tuple[str, ...] = tuple(
    sorted([*STEP_APPLY_FUNCTIONS.keys(), *CONTEXT_STEP_APPLY_FUNCTIONS.keys()])
)

__all__ = [
    "ALL_STEP_TYPES",
    "CONTEXT_STEP_APPLY_FUNCTIONS",
    "STEP_APPLY_FUNCTIONS",
    "ContextStepApplyFn",
    "StepApplyFn",
    "StepContext",
    "apply_aggregate",
    "apply_cast_column_types",
    "apply_derive_column",
    "apply_drop_columns",
    "apply_drop_null_rows",
    "apply_fill_nulls",
    "apply_filter_rows",
    "apply_join_datasets",
    "apply_limit_rows",
    "apply_parse_dates",
    "apply_pivot",
    "apply_remove_duplicates",
    "apply_rename_columns",
    "apply_replace_values",
    "apply_select_columns",
    "apply_sort_rows",
    "apply_split_column",
    "apply_trim_strings",
    "apply_union_datasets",
    "apply_unpivot",
]
