from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list


def validate_drop_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    config = ensure_config_keys(config, required={"columns"})
    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")

    unique_drop = list(dict.fromkeys(columns))
    remaining = [column for column in dataframe.columns if column not in set(unique_drop)]
    if not remaining:
        raise BadRequestError("drop_columns cannot remove all columns.")
    return columns


def apply_drop_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns = validate_drop_columns(dataframe, config)
    unique_drop = list(dict.fromkeys(columns))
    return dataframe.drop(columns=unique_drop).copy(), []
