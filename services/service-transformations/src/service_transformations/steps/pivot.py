from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.aggregate import SUPPORTED_AGGREGATIONS
from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError

# A pivot fans columns out by distinct value, so an unbounded cardinality column
# would produce an unusable frame. This bounds the blast radius.
MAX_PIVOT_COLUMNS = 200


def validate_pivot(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str], str, str, str]:
    config = ensure_config_keys(
        config, required={"index", "columns", "values"}, optional={"aggregation"}
    )

    index_columns = require_string_list(config["index"], field_name="config.index")
    ensure_columns_exist(dataframe, index_columns, field_name="config.index")

    pivot_column = config["columns"]
    if not isinstance(pivot_column, str) or not pivot_column.strip():
        raise BadRequestError("config.columns must be a non-empty string naming one column.")
    pivot_column = pivot_column.strip()
    ensure_columns_exist(dataframe, [pivot_column], field_name="config.columns")

    values_column = config["values"]
    if not isinstance(values_column, str) or not values_column.strip():
        raise BadRequestError("config.values must be a non-empty string naming one column.")
    values_column = values_column.strip()
    ensure_columns_exist(dataframe, [values_column], field_name="config.values")

    if pivot_column in index_columns:
        raise BadRequestError("config.columns cannot also appear in config.index.")
    if values_column in index_columns or values_column == pivot_column:
        raise BadRequestError("config.values must differ from config.index and config.columns.")

    aggregation = str(config.get("aggregation", "sum")).lower()
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise BadRequestError(
            f"config.aggregation must be one of: {', '.join(sorted(SUPPORTED_AGGREGATIONS))}."
        )

    distinct = int(dataframe[pivot_column].nunique(dropna=True))
    if distinct > MAX_PIVOT_COLUMNS:
        raise BadRequestError(
            f"Column '{pivot_column}' has {distinct} distinct values, which exceeds the "
            f"{MAX_PIVOT_COLUMNS}-column pivot limit."
        )

    return index_columns, pivot_column, values_column, aggregation


def apply_pivot(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    index_columns, pivot_column, values_column, aggregation = validate_pivot(dataframe, config)
    warnings: list[str] = []

    working = dataframe.copy()
    if aggregation in {"sum", "mean", "avg", "median", "std"}:
        working[values_column] = pd.to_numeric(working[values_column], errors="coerce")

    pivoted = working.pivot_table(
        index=index_columns,
        columns=pivot_column,
        values=values_column,
        aggfunc=SUPPORTED_AGGREGATIONS[aggregation],
        dropna=False,
    ).reset_index()

    # pivot_table leaves the pivot column's name on the column index; drop it so
    # downstream steps see a plain frame.
    pivoted.columns = [str(column) for column in pivoted.columns]
    pivoted.columns.name = None

    generated = [column for column in pivoted.columns if column not in index_columns]
    if not generated:
        warnings.append(f"Pivot on '{pivot_column}' produced no value columns.")

    return pivoted.reset_index(drop=True), warnings
