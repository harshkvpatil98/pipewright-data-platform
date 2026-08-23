from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_config_keys
from service_transformations.steps.context import StepContext
from shared_python.errors import BadRequestError

MAX_UNION_RESULT_ROWS = 5_000_000


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    config = ensure_config_keys(
        config, required={"other_dataset_id"}, optional={"deduplicate", "column_strategy"}
    )

    other_dataset_id = config["other_dataset_id"]
    if not isinstance(other_dataset_id, str) or not other_dataset_id.strip():
        raise BadRequestError("config.other_dataset_id must be a non-empty string.")
    try:
        uuid.UUID(other_dataset_id.strip())
    except ValueError as exc:
        raise BadRequestError("config.other_dataset_id must be a valid dataset id.") from exc

    deduplicate = config.get("deduplicate", False)
    if not isinstance(deduplicate, bool):
        raise BadRequestError("config.deduplicate must be a boolean.")

    strategy = str(config.get("column_strategy", "union")).lower()
    if strategy not in {"union", "intersect", "strict"}:
        raise BadRequestError("config.column_strategy must be 'union', 'intersect', or 'strict'.")

    return {
        "other_dataset_id": other_dataset_id.strip(),
        "deduplicate": deduplicate,
        "column_strategy": strategy,
    }


def validate_union_datasets(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    return _validate_config(config)


def apply_union_datasets(
    dataframe: pd.DataFrame, config: dict[str, Any], context: StepContext
) -> tuple[pd.DataFrame, list[str]]:
    settings = _validate_config(config)
    warnings: list[str] = []

    other = context.load_dataset(settings["other_dataset_id"])
    label = context.dataset_label(settings["other_dataset_id"])

    left_columns = [str(column) for column in dataframe.columns]
    right_columns = [str(column) for column in other.columns]
    only_left = [column for column in left_columns if column not in right_columns]
    only_right = [column for column in right_columns if column not in left_columns]

    strategy = settings["column_strategy"]
    if strategy == "strict" and (only_left or only_right):
        mismatch = ", ".join(sorted({*only_left, *only_right}))
        raise BadRequestError(
            f"Column sets do not match between the datasets (differing: {mismatch}). "
            "Use column_strategy 'union' or 'intersect' to combine them anyway."
        )

    left, right = dataframe, other
    if strategy == "intersect":
        shared = [column for column in left_columns if column in right_columns]
        if not shared:
            raise BadRequestError(f"'{label}' shares no columns with the current dataset.")
        left, right = dataframe[shared], other[shared]
        if only_left or only_right:
            warnings.append(f"Kept the {len(shared)} shared column(s); non-shared columns were dropped.")
    elif only_left or only_right:
        warnings.append(
            f"Datasets have different columns; missing values are null "
            f"(only here: {len(only_left)}, only in '{label}': {len(only_right)})."
        )

    combined = pd.concat([left, right], ignore_index=True, sort=False)

    if len(combined) > MAX_UNION_RESULT_ROWS:
        raise BadRequestError(
            f"Union produced {len(combined):,} rows, above the {MAX_UNION_RESULT_ROWS:,} limit."
        )

    if settings["deduplicate"]:
        before = len(combined)
        combined = combined.drop_duplicates().reset_index(drop=True)
        removed = before - len(combined)
        if removed:
            warnings.append(f"Removed {removed} duplicate row(s) after the union.")

    return combined.reset_index(drop=True), warnings
