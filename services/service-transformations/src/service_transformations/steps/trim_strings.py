from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list


def validate_trim_strings(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    config = ensure_config_keys(config, required={"columns"})
    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")
    return columns


def apply_trim_strings(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns = validate_trim_strings(dataframe, config)
    transformed = dataframe.copy()
    for column in columns:
        transformed[column] = transformed[column].map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
    return transformed, []
