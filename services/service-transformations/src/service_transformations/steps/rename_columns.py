from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_mapping


def validate_rename_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, str]:
    config = ensure_config_keys(config, required={"mappings"})
    mappings = require_mapping(config["mappings"], field_name="config.mappings")
    normalized_mappings: dict[str, str] = {}

    for old_name, new_name in mappings.items():
        if not isinstance(old_name, str) or not old_name.strip():
            raise BadRequestError("config.mappings keys must be non-empty strings.")
        if not isinstance(new_name, str) or not new_name.strip():
            raise BadRequestError(f"config.mappings['{old_name}'] must be a non-empty string.")
        normalized_mappings[old_name] = new_name.strip()

    ensure_columns_exist(dataframe, list(normalized_mappings.keys()), field_name="config.mappings")

    resulting_columns = [normalized_mappings.get(column, column) for column in dataframe.columns]
    duplicates = sorted({column for column in resulting_columns if resulting_columns.count(column) > 1})
    if duplicates:
        raise BadRequestError(
            f"rename_columns would create duplicate column name(s): {', '.join(duplicates)}."
        )

    return normalized_mappings


def apply_rename_columns(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    mappings = validate_rename_columns(dataframe, config)
    return dataframe.rename(columns=mappings).copy(), []
