from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError
from shared_python.words import listing

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

#: E1's functions, each the IR aggregate it is (`ir/pandas_aggregates.py` says
#: what each means) and what else it needs: "argument" (a number or text) or
#: "other_column". Kept apart from SUPPORTED_AGGREGATIONS, whose values are
#: pandas method names the pivot step hands to pandas.
EXTRA_AGGREGATIONS: dict[str, dict[str, Any]] = {
    "variance": {"ir": "variance", "numeric": True},
    "mode": {"ir": "mode"},
    "count_empty": {"ir": "count_null"},
    "nth": {"ir": "nth", "argument": "integer", "default": 1},
    "list": {"ir": "list_agg"},
    "join_text": {"ir": "string_agg", "argument": "text", "default": ", "},
    "percentile": {"ir": "percentile", "argument": "percent", "default": 50, "numeric": True},
    "first_quartile": {"ir": "percentile", "fixed": 0.25, "numeric": True},
    "third_quartile": {"ir": "percentile", "fixed": 0.75, "numeric": True},
    "range": {"ir": "range", "numeric": True},
    "product": {"ir": "product", "numeric": True},
    "any_true": {"ir": "any_true"},
    "all_true": {"ir": "all_true"},
    "correlation": {"ir": "corr", "other": True, "numeric": True},
    "covariance": {"ir": "covar", "other": True, "numeric": True},
    "weighted_average": {"ir": "weighted_avg", "other": True, "numeric": True},
}

ALL_AGGREGATIONS = frozenset(SUPPORTED_AGGREGATIONS) | frozenset(EXTRA_AGGREGATIONS)


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
        if not isinstance(function, str) or function.lower() not in ALL_AGGREGATIONS:
            raise BadRequestError(
                f"config.aggregations[{index}].function must be one of: "
                f"{', '.join(sorted(ALL_AGGREGATIONS))}."
            )

        function = function.lower()
        ensure_columns_exist(dataframe, [column], field_name=f"config.aggregations[{index}].column")
        extra = EXTRA_AGGREGATIONS.get(function, {})
        settings: dict[str, Any] = {}
        if extra.get("other"):
            other = entry.get("other_column")
            if not isinstance(other, str) or not other.strip():
                raise BadRequestError(f"config.aggregations[{index}]: {function.replace('_', ' ')} needs "
                                      "other_column, the second column it reads.")
            ensure_columns_exist(dataframe, [other], field_name=f"config.aggregations[{index}].other_column")
            settings["other_column"] = other
        if extra.get("argument"):
            settings["argument"] = _argument(entry.get("argument"), extra, index, function)

        if function in _NUMERIC_ONLY or extra.get("numeric"):
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

        aggregations.append({"column": column, "function": function, "alias": alias, **settings})

    collisions = sorted(set(group_by) & seen_aliases)
    if collisions:
        raise BadRequestError(f"Some result names are the same as the group_by columns: {listing(collisions)}. Rename them.")

    return group_by, aggregations


def _argument(raw: Any, extra: dict[str, Any], index: int, function: str) -> Any:
    label = f"config.aggregations[{index}].argument"
    if raw is None or raw == "":
        return extra["default"]
    if extra["argument"] == "text":
        return str(raw)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BadRequestError(f"{label} for {function.replace('_', ' ')} must be a number.") from None
    if extra["argument"] == "percent" and not 0 <= value <= 100:
        raise BadRequestError(f"{label}: a percentile is between 0 and 100.")
    if extra["argument"] == "integer":
        if value < 1 or value != int(value):
            raise BadRequestError(f"{label}: the nth value counts whole rows from 1.")
        return int(value)
    return value


def ir_call(spec: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """The IR function an aggregation entry is, and its arguments past the column."""
    from service_transformations.ir.expressions import Column, Literal
    from shared_python.types import FLOAT64, INT64, STRING

    extra = EXTRA_AGGREGATIONS[spec["function"]]
    if extra.get("other"):
        return extra["ir"], (Column(spec["other_column"]),)
    if "fixed" in extra:
        return extra["ir"], (Literal(extra["fixed"], FLOAT64),)
    if extra.get("argument") == "percent":
        return extra["ir"], (Literal(float(spec["argument"]) / 100, FLOAT64),)
    if extra.get("argument") == "integer":
        return extra["ir"], (Literal(int(spec["argument"]), INT64),)
    if extra.get("argument") == "text":
        return extra["ir"], (Literal(str(spec["argument"]), STRING),)
    return extra["ir"], ()


def _extra(frame: pd.DataFrame, keys: list[str], spec: dict[str, Any]) -> Any:
    from service_transformations.ir.expressions import Column, Literal
    from service_transformations.ir.pandas_aggregates import aggregate

    function, rest = ir_call(spec)
    columns = [spec["column"], *[arg.name for arg in rest if isinstance(arg, Column)]]
    constants = [arg.value for arg in rest if isinstance(arg, Literal)]
    return aggregate(frame, keys, function, columns, constants)


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
            if spec["function"] in EXTRA_AGGREGATIONS:
                row[spec["alias"]] = _extra(dataframe, [], spec)
                continue
            series = _series_for(spec["column"], spec["function"], dataframe)
            row[spec["alias"]] = getattr(series, SUPPORTED_AGGREGATIONS[spec["function"]])()
        warnings.append("No group_by columns were provided, so the result is a single summary row.")
        return pd.DataFrame([row]), warnings

    grouped = dataframe.groupby(group_by, dropna=False, sort=True)
    output = pd.DataFrame(grouped.size().index.to_frame(index=False))

    for spec in aggregations:
        column, function, alias = spec["column"], spec["function"], spec["alias"]
        if function in EXTRA_AGGREGATIONS:
            values = _extra(dataframe, group_by, spec).rename(alias).reset_index()
            output = output.merge(values, on=group_by, how="left")
            continue
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
