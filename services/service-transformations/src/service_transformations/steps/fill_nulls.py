from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_FILL_NULL_STRATEGIES,
    ensure_columns_exist,
    ensure_config_keys,
    is_numeric_series,
    require_string_list,
)


def validate_fill_nulls(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[str, list[str], Any]:
    config = ensure_config_keys(config, required={"strategy", "columns"}, optional={"constant_value"})
    strategy = config["strategy"]
    if not isinstance(strategy, str) or strategy not in ALLOWED_FILL_NULL_STRATEGIES:
        allowed = ", ".join(sorted(ALLOWED_FILL_NULL_STRATEGIES))
        raise BadRequestError(f"config.strategy must be one of: {allowed}.")

    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")

    if strategy in {"mean", "median"}:
        non_numeric = [column for column in columns if not is_numeric_series(dataframe[column])]
        if non_numeric:
            raise BadRequestError(
                f"{strategy} fill is only supported for numeric columns: {', '.join(non_numeric)}."
            )

    if strategy == "constant" and "constant_value" not in config:
        raise BadRequestError("config.constant_value is required when strategy is 'constant'.")
    constant_value = config.get("constant_value")

    return strategy, columns, constant_value


def apply_fill_nulls(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    strategy, columns, constant_value = validate_fill_nulls(dataframe, config)
    transformed = dataframe.copy()
    warnings: list[str] = []

    for column in columns:
        series = transformed[column]
        fill_value = constant_value

        if strategy == "mean":
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if numeric.empty:
                warnings.append(f"Column '{column}' has no numeric values to compute a mean fill.")
                continue
            fill_value = float(numeric.mean())
        elif strategy == "median":
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if numeric.empty:
                warnings.append(f"Column '{column}' has no numeric values to compute a median fill.")
                continue
            fill_value = float(numeric.median())
        elif strategy == "mode":
            modes = series.dropna().mode(dropna=True)
            if modes.empty:
                warnings.append(f"Column '{column}' has no non-null values to compute a mode fill.")
                continue
            fill_value = modes.iloc[0]

        transformed[column] = series.fillna(fill_value)

    return transformed, warnings
