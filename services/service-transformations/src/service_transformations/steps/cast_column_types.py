from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_CAST_TARGET_TYPES,
    ensure_columns_exist,
    ensure_config_keys,
    require_mapping,
)


def validate_cast_column_types(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, str]:
    config = ensure_config_keys(config, required={"mappings"})
    mappings = require_mapping(config["mappings"], field_name="config.mappings")
    normalized_mappings: dict[str, str] = {}

    for column_name, target_type in mappings.items():
        if not isinstance(column_name, str) or not column_name.strip():
            raise BadRequestError("config.mappings keys must be non-empty strings.")
        if not isinstance(target_type, str) or target_type not in ALLOWED_CAST_TARGET_TYPES:
            allowed_types = ", ".join(sorted(ALLOWED_CAST_TARGET_TYPES))
            raise BadRequestError(
                f"config.mappings['{column_name}'] must be one of: {allowed_types}."
            )
        normalized_mappings[column_name] = target_type

    ensure_columns_exist(dataframe, list(normalized_mappings.keys()), field_name="config.mappings")
    return normalized_mappings


def apply_cast_column_types(
    dataframe: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, list[str]]:
    mappings = validate_cast_column_types(dataframe, config)
    transformed = dataframe.copy()
    warnings: list[str] = []

    for column_name, target_type in mappings.items():
        series = transformed[column_name]
        if target_type == "string":
            transformed[column_name] = series.map(lambda value: None if pd.isna(value) else str(value))
            continue

        if target_type == "int":
            numeric = pd.to_numeric(series, errors="coerce")
            fractional_mask = numeric.notna() & ((numeric % 1) != 0)
            numeric = numeric.mask(fractional_mask)
            introduced_nulls = int((series.notna() & numeric.isna()).sum())
            transformed[column_name] = numeric.astype("Int64")
            if introduced_nulls:
                warnings.append(
                    f"Casting column '{column_name}' to int introduced {introduced_nulls} null value(s)."
                )
            continue

        if target_type == "float":
            numeric = pd.to_numeric(series, errors="coerce")
            introduced_nulls = int((series.notna() & numeric.isna()).sum())
            transformed[column_name] = numeric
            if introduced_nulls:
                warnings.append(
                    f"Casting column '{column_name}' to float introduced {introduced_nulls} null value(s)."
                )
            continue

        if target_type == "datetime":
            parsed = pd.to_datetime(series, errors="coerce")
            introduced_nulls = int((series.notna() & parsed.isna()).sum())
            transformed[column_name] = parsed
            if introduced_nulls:
                warnings.append(
                    f"Casting column '{column_name}' to datetime introduced {introduced_nulls} null value(s)."
                )
            continue

        parsed_boolean, introduced_nulls = _cast_boolean_series(series)
        transformed[column_name] = parsed_boolean
        if introduced_nulls:
            warnings.append(
                f"Casting column '{column_name}' to boolean introduced {introduced_nulls} null value(s)."
            )

    return transformed, warnings


def _cast_boolean_series(series: pd.Series) -> tuple[pd.Series, int]:
    parsed_values: list[object] = []
    introduced_nulls = 0

    for value in series.tolist():
        parsed_value, invalid = _parse_boolean_value(value)
        if invalid:
            introduced_nulls += 1
        parsed_values.append(parsed_value)

    return pd.Series(parsed_values, index=series.index, dtype="boolean"), introduced_nulls


def _parse_boolean_value(value: object) -> tuple[object, bool]:
    if pd.isna(value):
        return pd.NA, False
    if isinstance(value, bool):
        return value, False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value), False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "t", "yes", "y", "1"}:
            return True, False
        if normalized in {"false", "f", "no", "n", "0"}:
            return False, False
    return pd.NA, True
