from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list


def validate_select_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    config = ensure_config_keys(config, required={"columns"})
    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")
    return list(dict.fromkeys(columns))


def apply_select_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns = validate_select_columns(dataframe, config)
    removed_count = max(len(dataframe.columns) - len(columns), 0)
    warnings: list[str] = []
    if removed_count:
        warnings.append(
            f"select_columns removed {removed_count} column(s) from the preview dataset."
        )
    return dataframe.loc[:, columns].copy(), warnings
