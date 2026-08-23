from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from service_transformations.steps.context import StepContext
from shared_python.errors import BadRequestError

SUPPORTED_JOIN_TYPES = ("inner", "left", "right", "outer")

# A many-to-many join can multiply row counts without warning, so results are
# capped and the operator is told rather than silently handed a huge frame.
MAX_JOIN_RESULT_ROWS = 5_000_000


def _validate_config(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    config = ensure_config_keys(
        config,
        required={"right_dataset_id", "left_on", "right_on"},
        optional={"how", "suffix", "select_right_columns"},
    )

    right_dataset_id = config["right_dataset_id"]
    if not isinstance(right_dataset_id, str) or not right_dataset_id.strip():
        raise BadRequestError("config.right_dataset_id must be a non-empty string.")
    try:
        uuid.UUID(right_dataset_id.strip())
    except ValueError as exc:
        raise BadRequestError("config.right_dataset_id must be a valid dataset id.") from exc

    left_on = require_string_list(config["left_on"], field_name="config.left_on")
    right_on = require_string_list(config["right_on"], field_name="config.right_on")
    if len(left_on) != len(right_on):
        raise BadRequestError("config.left_on and config.right_on must have the same number of columns.")
    ensure_columns_exist(dataframe, left_on, field_name="config.left_on")

    how = str(config.get("how", "inner")).lower()
    if how not in SUPPORTED_JOIN_TYPES:
        raise BadRequestError(f"config.how must be one of: {', '.join(SUPPORTED_JOIN_TYPES)}.")

    suffix = config.get("suffix", "_right")
    if not isinstance(suffix, str) or not suffix.strip():
        raise BadRequestError("config.suffix must be a non-empty string.")

    select_right = config.get("select_right_columns")
    if select_right is not None:
        select_right = require_string_list(select_right, field_name="config.select_right_columns")

    return {
        "right_dataset_id": right_dataset_id.strip(),
        "left_on": left_on,
        "right_on": right_on,
        "how": how,
        "suffix": suffix.strip(),
        "select_right_columns": select_right,
    }


def validate_join_datasets(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Structural validation only; the right frame is not loaded until execution."""
    return _validate_config(dataframe, config)


def apply_join_datasets(
    dataframe: pd.DataFrame, config: dict[str, Any], context: StepContext
) -> tuple[pd.DataFrame, list[str]]:
    settings = _validate_config(dataframe, config)
    warnings: list[str] = []

    right = context.load_dataset(settings["right_dataset_id"])
    label = context.dataset_label(settings["right_dataset_id"])

    ensure_columns_exist(right, settings["right_on"], field_name="config.right_on")

    if settings["select_right_columns"] is not None:
        keep = list(dict.fromkeys([*settings["right_on"], *settings["select_right_columns"]]))
        ensure_columns_exist(right, keep, field_name="config.select_right_columns")
        right = right[keep]

    left_rows = int(len(dataframe))
    right_rows = int(len(right))

    # Guard against an accidental cartesian explosion before doing the work.
    left_key_dupes = int(dataframe.duplicated(subset=settings["left_on"]).sum())
    right_key_dupes = int(right.duplicated(subset=settings["right_on"]).sum())
    if left_key_dupes and right_key_dupes:
        estimated = left_rows * max(1, right_rows // max(1, right_rows - right_key_dupes))
        if estimated > MAX_JOIN_RESULT_ROWS:
            raise BadRequestError(
                "This join has duplicate keys on both sides and would produce an unmanageable number "
                "of rows. Aggregate or deduplicate one side first."
            )
        warnings.append(
            "Join keys are non-unique on both sides, so matching rows are multiplied (many-to-many)."
        )

    try:
        merged = dataframe.merge(
            right,
            how=settings["how"],
            left_on=settings["left_on"],
            right_on=settings["right_on"],
            suffixes=("", settings["suffix"]),
        )
    except ValueError as exc:
        raise BadRequestError(f"Join failed: {exc}") from exc

    if len(merged) > MAX_JOIN_RESULT_ROWS:
        raise BadRequestError(
            f"Join produced {len(merged):,} rows, above the {MAX_JOIN_RESULT_ROWS:,} limit."
        )

    if merged.empty and left_rows and right_rows:
        warnings.append(f"Join with '{label}' matched no rows; check that the key columns line up.")
    elif settings["how"] == "inner" and len(merged) < left_rows:
        warnings.append(
            f"Inner join dropped {left_rows - len(merged)} unmatched row(s) from the left dataset."
        )

    return merged.reset_index(drop=True), warnings
