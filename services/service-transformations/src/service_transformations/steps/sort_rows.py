from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError


def validate_sort_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str], list[bool], str]:
    config = ensure_config_keys(config, required={"columns"}, optional={"ascending", "na_position"})

    columns = require_string_list(config["columns"], field_name="config.columns")
    ensure_columns_exist(dataframe, columns, field_name="config.columns")

    raw_ascending = config.get("ascending", True)
    if isinstance(raw_ascending, bool):
        ascending = [raw_ascending] * len(columns)
    elif isinstance(raw_ascending, list):
        if len(raw_ascending) != len(columns):
            raise BadRequestError("config.ascending must be a boolean or a list matching config.columns.")
        if not all(isinstance(item, bool) for item in raw_ascending):
            raise BadRequestError("config.ascending list must contain only booleans.")
        ascending = list(raw_ascending)
    else:
        raise BadRequestError("config.ascending must be a boolean or a list of booleans.")

    na_position = config.get("na_position", "last")
    if na_position not in {"first", "last"}:
        raise BadRequestError("config.na_position must be 'first' or 'last'.")

    return columns, ascending, na_position


def apply_sort_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    columns, ascending, na_position = validate_sort_rows(dataframe, config)
    sorted_frame = dataframe.sort_values(
        by=columns, ascending=ascending, na_position=na_position, kind="stable"
    ).reset_index(drop=True)
    return sorted_frame, []
