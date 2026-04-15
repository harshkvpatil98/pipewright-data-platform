from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_NULL_DROP_HOW,
    ensure_columns_exist,
    ensure_config_keys,
    require_string_list,
)


def validate_drop_null_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str] | None, str]:
    config = ensure_config_keys(config, required={"how"}, optional={"columns"})
    how = config["how"]
    if not isinstance(how, str) or how not in ALLOWED_NULL_DROP_HOW:
        allowed = ", ".join(sorted(ALLOWED_NULL_DROP_HOW))
        raise BadRequestError(f"config.how must be one of: {allowed}.")

    columns: list[str] | None = None
    if "columns" in config and config["columns"] is not None:
        columns = require_string_list(config["columns"], field_name="config.columns")
        ensure_columns_exist(dataframe, columns, field_name="config.columns")

    return columns, how


def apply_drop_null_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns, how = validate_drop_null_rows(dataframe, config)
    transformed = dataframe.dropna(subset=columns, how=how).copy()
    return transformed, []
