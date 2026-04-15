from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from math import isnan
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


def infer_schema(*, dataframe: pd.DataFrame) -> dict[str, Any]:
    ordered_columns = [str(column) for column in dataframe.columns]
    return {
        'columns': [
            {
                'name': column,
                'inferred_type': _infer_series_type(dataframe[column]),
                'nullable': bool(dataframe[column].isna().any()),
            }
            for column in ordered_columns
        ],
        'ordered_columns': ordered_columns,
    }


def build_preview(*, dataframe: pd.DataFrame, limit: int) -> dict[str, Any]:
    ordered_columns = [str(column) for column in dataframe.columns]
    preview_frame = dataframe.head(limit)
    rows = [
        {column: _json_safe_value(value) for column, value in row.items()}
        for row in preview_frame.to_dict(orient='records')
    ]
    return {'columns': ordered_columns, 'rows': rows}


def build_profile(*, dataframe: pd.DataFrame, sample_limit: int, file_size_bytes: int) -> dict[str, Any]:
    row_count = int(len(dataframe))
    column_count = int(len(dataframe.columns))
    duplicate_row_count = int(dataframe.duplicated().sum()) if row_count else 0
    duplicate_row_percentage = round((duplicate_row_count / row_count) * 100, 2) if row_count else 0.0
    total_null_cells = int(dataframe.isna().sum().sum()) if row_count and column_count else 0
    total_cells = row_count * column_count
    completeness_score = round(((total_cells - total_null_cells) / total_cells) * 100, 2) if total_cells else 100.0

    profile_columns = []
    high_null_columns: list[str] = []
    constant_value_columns: list[str] = []
    potential_id_columns: list[str] = []
    mixed_type_suspicions: list[str] = []

    for column in dataframe.columns:
        series = dataframe[column]
        non_null = series.dropna()
        null_count = int(series.isna().sum())
        non_null_count = int(len(non_null))
        unique_count = int(non_null.nunique(dropna=True))
        null_percentage = round((null_count / row_count) * 100, 2) if row_count else 0.0
        unique_percentage = round((unique_count / non_null_count) * 100, 2) if non_null_count else 0.0
        inferred_type = _infer_series_type(series)
        sample_values = _sample_values(non_null, sample_limit)
        mixed_type_suspected = _has_mixed_types(non_null)
        possible_identifier = _is_possible_identifier(
            name=str(column),
            unique_count=unique_count,
            non_null_count=non_null_count,
            null_count=null_count,
        )

        if null_percentage >= 50.0:
            high_null_columns.append(str(column))
        if unique_count == 1 and non_null_count > 0:
            constant_value_columns.append(str(column))
        if possible_identifier:
            potential_id_columns.append(str(column))
        if mixed_type_suspected:
            mixed_type_suspicions.append(str(column))

        min_value = max_value = mean_value = std_value = None
        min_length = max_length = None

        numeric_series = pd.to_numeric(non_null, errors='coerce').dropna()
        if not numeric_series.empty:
            min_value = _json_safe_value(numeric_series.min())
            max_value = _json_safe_value(numeric_series.max())
            mean_value = _safe_float(numeric_series.mean())
            std_value = _safe_float(numeric_series.std(ddof=1))

        if inferred_type in {'string', 'mixed', 'object'}:
            string_lengths = [len(str(value)) for value in non_null]
            if string_lengths:
                min_length = min(string_lengths)
                max_length = max(string_lengths)

        profile_columns.append(
            {
                'name': str(column),
                'inferred_type': inferred_type,
                'null_count': null_count,
                'null_percentage': null_percentage,
                'unique_count': unique_count,
                'unique_percentage': unique_percentage,
                'sample_values': sample_values,
                'min_value': min_value,
                'max_value': max_value,
                'mean_value': mean_value,
                'std_value': std_value,
                'min_length': min_length,
                'max_length': max_length,
                'possible_identifier': possible_identifier,
                'mixed_type_suspected': mixed_type_suspected,
            }
        )

    return {
        'file_size_bytes': file_size_bytes,
        'row_count': row_count,
        'column_count': column_count,
        'duplicate_row_count': duplicate_row_count,
        'duplicate_row_percentage': duplicate_row_percentage,
        'total_null_cells': total_null_cells,
        'completeness_score': completeness_score,
        'columns': profile_columns,
        'quality_flags': {
            'high_null_columns': high_null_columns,
            'constant_value_columns': constant_value_columns,
            'potential_id_columns': potential_id_columns,
            'mixed_type_suspicions': mixed_type_suspicions,
        },
    }


def _infer_series_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return 'empty'
    if is_bool_dtype(series):
        return 'bool'
    if is_integer_dtype(series):
        return 'int'
    if is_numeric_dtype(series):
        return 'float'
    if is_datetime64_any_dtype(series):
        return 'datetime'
    if is_string_dtype(series):
        return 'string'
    if is_object_dtype(series):
        python_types = {type(value).__name__ for value in non_null}
        if python_types <= {'str'}:
            return 'string'
        if python_types <= {'dict'}:
            return 'object'
        if python_types <= {'bool'}:
            return 'bool'
        if python_types <= {'int'}:
            return 'int'
        if python_types <= {'int', 'float'}:
            return 'float'
        return 'mixed' if len(python_types) > 1 else python_types.pop().lower()
    return 'string'


def _sample_values(series: pd.Series, sample_limit: int) -> list[Any]:
    samples: list[Any] = []
    for value in series.tolist():
        normalized = _json_safe_value(value)
        if normalized not in samples:
            samples.append(normalized)
        if len(samples) >= sample_limit:
            break
    return samples


def _has_mixed_types(series: pd.Series) -> bool:
    python_types = {type(value).__name__ for value in series.tolist()}
    return len(python_types) > 1


def _is_possible_identifier(*, name: str, unique_count: int, non_null_count: int, null_count: int) -> bool:
    normalized_name = name.lower()
    if non_null_count == 0:
        return False
    if normalized_name == 'id' or normalized_name.endswith('_id'):
        return unique_count == non_null_count and null_count == 0
    return unique_count == non_null_count and non_null_count >= 3 and null_count == 0


def _json_safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, 'item') and callable(value.item):
        try:
            return _json_safe_value(value.item())
        except ValueError:
            pass
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return value


def _safe_float(value: float | None) -> float | None:
    if value is None or pd.isna(value) or isnan(value):
        return None
    return round(float(value), 4)
