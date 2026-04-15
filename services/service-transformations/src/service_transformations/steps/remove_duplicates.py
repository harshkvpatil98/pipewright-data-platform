from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_transformations.steps.common import (
    ALLOWED_DUPLICATE_KEEP,
    ensure_columns_exist,
    ensure_config_keys,
    require_string_list,
)


def validate_remove_duplicates(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str] | None, str]:
    config = ensure_config_keys(config, required=set(), optional={"subset", "keep"})
    keep = config.get("keep", "first")
    if not isinstance(keep, str) or keep not in ALLOWED_DUPLICATE_KEEP:
        allowed = ", ".join(sorted(ALLOWED_DUPLICATE_KEEP))
        raise BadRequestError(f"config.keep must be one of: {allowed}.")

    subset: list[str] | None = None
    if config.get("subset") is not None:
        subset = require_string_list(config["subset"], field_name="config.subset")
        ensure_columns_exist(dataframe, subset, field_name="config.subset")

    return subset, keep


def apply_remove_duplicates(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    subset, keep = validate_remove_duplicates(dataframe, config)
    if keep == "none":
        duplicated_mask = dataframe.duplicated(subset=subset, keep=False)
        return dataframe.loc[~duplicated_mask].copy(), []
    return dataframe.drop_duplicates(subset=subset, keep=keep).copy(), []
