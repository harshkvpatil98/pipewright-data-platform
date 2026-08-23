from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError

# Aggregations that map to a pandas groupby function and are meaningful in a UI.
SUPPORTED_AGGREGATIONS: dict[str, str] = {
    "sum": "sum",
    "mean": "mean",
    "avg": "mean",
    "min": "min",
    "max": "max",
    "count": "count",
    "count_distinct": "nunique",
    "median": "median",
    "std": "std",
    "first": "first",
    "last": "last",
}

_NUMERIC_ONLY = {"sum", "mean", "avg", "median", "std"}


def validate_aggregate(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    config = ensure_config_keys(config, required={"aggregations"}, optional={"group_by"})

    group_by = require_string_list(config.get("group_by", []), field_name="config.group_by", allow_empty=True)
    if group_by:
        ensure_columns_exist(dataframe, group_by, field_name="config.group_by")

    raw_aggregations = config["aggregations"]
    if not isinstance(raw_aggregations, list) or not raw_aggregations:
        raise BadRequestError("config.aggregations must be a non-empty list.")

    aggregations: list[dict[str, str]] = []
    seen_aliases: set[str] = set()

    for index, entry in enumerate(raw_aggregations, start=1):
        if not isinstance(entry, dict):
            raise BadRequestError(f"config.aggregations[{index}] must be an object.")

        column = entry.get("column")
        function = entry.get("function")
        if not isinstance(column, str) or not column.strip():
            raise BadRequestError(f"config.aggregations[{index}].column must be a non-empty string.")
        if not isinstance(function, str) or function.lower() not in SUPPORTED_AGGREGATIONS:
            raise BadRequestError(
                f"config.aggregations[{index}].function must be one of: "
                f"{', '.join(sorted(SUPPORTED_AGGREGATIONS))}."
            )

        function = function.lower()
        ensure_columns_exist(dataframe, [column], field_name=f"config.aggregations[{index}].column")

        if function in _NUMERIC_ONLY:
            numeric = pd.to_numeric(dataframe[column], errors="coerce")
            if numeric.notna().sum() == 0 and len(dataframe) > 0:
                raise BadRequestError(
                    f"Column '{column}' has no numeric values, so '{function}' cannot be applied."
                )

        alias = entry.get("alias") or f"{column}_{function}"
        if not isinstance(alias, str) or not alias.strip():
            raise BadRequestError(f"config.aggregations[{index}].alias must be a non-empty string.")
        alias = alias.strip()
        if alias in seen_aliases:
            raise BadRequestError(f"Duplicate aggregation output name '{alias}'.")
        seen_aliases.add(alias)

        aggregations.append({"column": column, "function": function, "alias": alias})

    collisions = sorted(set(group_by) & seen_aliases)
    if collisions:
        raise BadRequestError(f"Aggregation output name(s) collide with group_by columns: {', '.join(collisions)}.")

    return group_by, aggregations


def apply_aggregate(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    group_by, aggregations = validate_aggregate(dataframe, config)
    warnings: list[str] = []

    def _series_for(column: str, function: str, frame: pd.DataFrame) -> pd.Series:
        series = frame[column]
        return pd.to_numeric(series, errors="coerce") if function in _NUMERIC_ONLY else series

    if not group_by:
        # No grouping: collapse the whole frame to a single summary row.
        row: dict[str, Any] = {}
        for spec in aggregations:
            series = _series_for(spec["column"], spec["function"], dataframe)
            row[spec["alias"]] = getattr(series, SUPPORTED_AGGREGATIONS[spec["function"]])()
        warnings.append("No group_by columns were provided, so the result is a single summary row.")
        return pd.DataFrame([row]), warnings

    grouped = dataframe.groupby(group_by, dropna=False, sort=True)
    output = pd.DataFrame(grouped.size().index.to_frame(index=False))

    for spec in aggregations:
        column, function, alias = spec["column"], spec["function"], spec["alias"]
        working = dataframe[[*group_by, column]].copy()
        if function in _NUMERIC_ONLY:
            working[column] = pd.to_numeric(working[column], errors="coerce")
        aggregated = (
            working.groupby(group_by, dropna=False, sort=True)[column]
            .agg(SUPPORTED_AGGREGATIONS[function])
            .reset_index()
            .rename(columns={column: alias})
        )
        output = output.merge(aggregated, on=group_by, how="left")

    if output.empty:
        warnings.append("Aggregation produced no rows because the input was empty.")

    return output.reset_index(drop=True), warnings
