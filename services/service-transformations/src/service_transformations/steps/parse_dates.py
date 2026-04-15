from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_PARSE_DATE_ERRORS,
    count_introduced_nulls,
    ensure_columns_exist,
    ensure_config_keys,
    require_string_list,
)


def validate_parse_dates(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str], str | None, str]:
    config = ensure_config_keys(config, required={"columns"}, optional={"format", "errors"})
    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")

    date_format = config.get("format")
    if date_format is not None and not isinstance(date_format, str):
        raise BadRequestError("config.format must be a string when provided.")

    errors = config.get("errors", "coerce")
    if not isinstance(errors, str) or errors not in ALLOWED_PARSE_DATE_ERRORS:
        allowed = ", ".join(sorted(ALLOWED_PARSE_DATE_ERRORS))
        raise BadRequestError(f"config.errors must be one of: {allowed}.")

    fmt = date_format.strip() if isinstance(date_format, str) else None
    return columns, fmt, errors


def apply_parse_dates(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns, fmt, errors = validate_parse_dates(dataframe, config)
    transformed = dataframe.copy()
    warnings: list[str] = []

    kwargs: dict[str, Any] = {"errors": errors}
    if fmt:
        kwargs["format"] = fmt

    for column in columns:
        series = transformed[column]
        if errors == "raise":
            try:
                parsed = pd.to_datetime(series, **kwargs)
            except (ValueError, TypeError) as exc:
                raise BadRequestError(f"parse_dates failed for column '{column}': {exc}") from exc
        else:
            parsed = pd.to_datetime(series, **kwargs)

        if errors == "coerce":
            introduced = count_introduced_nulls(series, parsed)
            if introduced:
                warnings.append(
                    f"parse_dates with coerce produced {introduced} null value(s) in column '{column}'."
                )
        transformed[column] = parsed

    return transformed, warnings
