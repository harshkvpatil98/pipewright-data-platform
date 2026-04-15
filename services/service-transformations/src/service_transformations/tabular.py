from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_integer_dtype,
    is_numeric_dtype,
    is_object_dtype,
    is_string_dtype,
)

from service_transformations.schemas import TransformationPreviewSchema


def build_schema_summary(dataframe: pd.DataFrame) -> TransformationPreviewSchema:
    ordered_columns = [str(column) for column in dataframe.columns]
    return TransformationPreviewSchema(
        ordered_columns=ordered_columns,
        columns=[
            {
                "name": column,
                "inferred_type": infer_series_type(dataframe[column]),
            }
            for column in ordered_columns
        ],
    )


def infer_series_type(series: pd.Series) -> str:
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
    if is_object_dtype(series):
        python_types = {type(value).__name__ for value in non_null}
        if python_types <= {"str"}:
            return "string"
        if python_types <= {"bool"}:
            return "boolean"
        if python_types <= {"int"}:
            return "int"
        if python_types <= {"int", "float"}:
            return "float"
        return "mixed" if len(python_types) > 1 else python_types.pop().lower()
    return "string"


def is_numeric_column(series: pd.Series) -> bool:
    return infer_series_type(series) in {"int", "float"}


def is_string_compatible_column(series: pd.Series) -> bool:
    return infer_series_type(series) in {"string", "mixed", "object"}


def json_preview_rows(dataframe: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    preview_frame = dataframe.head(limit)
    rows = []
    for row in preview_frame.to_dict(orient="records"):
        rows.append({str(column): _json_safe_value(value) for column, value in row.items()})
    return rows


def _json_safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_safe_value(value.item())
        except ValueError:
            pass
    if pd.isna(value):
        return None
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return value
