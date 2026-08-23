from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_config_keys
from shared_python.errors import BadRequestError

MAX_LIMIT = 10_000_000


def validate_limit_rows(config: dict[str, Any]) -> tuple[int, int]:
    config = ensure_config_keys(config, required={"count"}, optional={"offset"})

    count = config["count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise BadRequestError("config.count must be a positive integer.")
    if count > MAX_LIMIT:
        raise BadRequestError(f"config.count cannot exceed {MAX_LIMIT:,}.")

    offset = config.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise BadRequestError("config.offset must be a non-negative integer.")

    return count, offset


def apply_limit_rows(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    count, offset = validate_limit_rows(config)
    warnings: list[str] = []

    if offset >= len(dataframe) and len(dataframe) > 0:
        warnings.append(f"Offset {offset} is beyond the {len(dataframe)} available rows, so no rows remain.")

    limited = dataframe.iloc[offset : offset + count].reset_index(drop=True)
    return limited, warnings
