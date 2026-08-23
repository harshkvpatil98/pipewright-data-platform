from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError


def validate_split_column(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[str, str, list[str], bool]:
    config = ensure_config_keys(
        config, required={"column", "delimiter", "into"}, optional={"drop_original"}
    )

    column = config["column"]
    if not isinstance(column, str) or not column.strip():
        raise BadRequestError("config.column must be a non-empty string.")
    column = column.strip()
    ensure_columns_exist(dataframe, [column], field_name="config.column")

    delimiter = config["delimiter"]
    if not isinstance(delimiter, str) or delimiter == "":
        raise BadRequestError("config.delimiter must be a non-empty string.")

    into = require_string_list(config["into"], field_name="config.into")
    duplicates = sorted({name for name in into if into.count(name) > 1})
    if duplicates:
        raise BadRequestError(f"config.into contains duplicate name(s): {', '.join(duplicates)}.")

    drop_original = config.get("drop_original", False)
    if not isinstance(drop_original, bool):
        raise BadRequestError("config.drop_original must be a boolean.")

    existing = sorted(set(into) & set(str(c) for c in dataframe.columns) - ({column} if drop_original else set()))
    if existing:
        raise BadRequestError(f"config.into would overwrite existing column(s): {', '.join(existing)}.")

    return column, delimiter, into, drop_original


def apply_split_column(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    column, delimiter, into, drop_original = validate_split_column(dataframe, config)
    warnings: list[str] = []

    working = dataframe.copy()
    # n=len-1 keeps any extra delimiters inside the final part rather than dropping data.
    parts = working[column].astype("string").str.split(delimiter, n=len(into) - 1, expand=True)

    for position, name in enumerate(into):
        working[name] = parts[position] if position in parts.columns else pd.NA

    produced = len(parts.columns)
    if produced < len(into):
        warnings.append(
            f"Splitting '{column}' produced at most {produced} part(s); "
            f"the remaining target column(s) are null."
        )

    if drop_original:
        working = working.drop(columns=[column])

    return working.reset_index(drop=True), warnings
