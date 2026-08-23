from __future__ import annotations

import re
from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys
from shared_python.errors import BadRequestError

MAX_PATTERN_LENGTH = 500


def validate_replace_values(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[str, list[dict[str, Any]], bool]:
    config = ensure_config_keys(config, required={"column", "replacements"}, optional={"use_regex"})

    column = config["column"]
    if not isinstance(column, str) or not column.strip():
        raise BadRequestError("config.column must be a non-empty string.")
    column = column.strip()
    ensure_columns_exist(dataframe, [column], field_name="config.column")

    use_regex = config.get("use_regex", False)
    if not isinstance(use_regex, bool):
        raise BadRequestError("config.use_regex must be a boolean.")

    raw = config["replacements"]
    if not isinstance(raw, list) or not raw:
        raise BadRequestError("config.replacements must be a non-empty list.")

    replacements: list[dict[str, Any]] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise BadRequestError(f"config.replacements[{index}] must be an object.")
        if "find" not in entry or "replace_with" not in entry:
            raise BadRequestError(
                f"config.replacements[{index}] must include 'find' and 'replace_with'."
            )
        find = entry["find"]
        if not isinstance(find, str):
            raise BadRequestError(f"config.replacements[{index}].find must be a string.")
        if use_regex:
            if len(find) > MAX_PATTERN_LENGTH:
                raise BadRequestError(
                    f"config.replacements[{index}].find exceeds {MAX_PATTERN_LENGTH} characters."
                )
            try:
                re.compile(find)
            except re.error as exc:
                raise BadRequestError(
                    f"config.replacements[{index}].find is not a valid regular expression: {exc}."
                ) from exc

        replace_with = entry["replace_with"]
        if replace_with is not None and not isinstance(replace_with, (str, int, float, bool)):
            raise BadRequestError(
                f"config.replacements[{index}].replace_with must be a string, number, boolean, or null."
            )
        replacements.append({"find": find, "replace_with": replace_with})

    return column, replacements, use_regex


def apply_replace_values(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    column, replacements, use_regex = validate_replace_values(dataframe, config)
    warnings: list[str] = []

    working = dataframe.copy()
    series = working[column].astype("string")
    total_changed = 0

    for replacement in replacements:
        before = series.copy()
        series = series.str.replace(
            replacement["find"],
            "" if replacement["replace_with"] is None else str(replacement["replace_with"]),
            regex=use_regex,
        )
        total_changed += int((before.fillna("") != series.fillna("")).sum())

    if total_changed == 0 and len(working) > 0:
        warnings.append(f"No values in '{column}' matched any replacement rule.")

    working[column] = series
    return working, warnings
