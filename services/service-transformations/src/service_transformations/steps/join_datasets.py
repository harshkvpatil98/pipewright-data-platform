from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from service_transformations.steps.context import StepContext
from shared_python.errors import BadRequestError
from shared_python.words import count_of
from service_transformations.steps.join_size import MAX_JOIN_RESULT_ROWS, check_join

SUPPORTED_JOIN_TYPES = ("inner", "left", "right", "outer", "full", "cross", "semi", "anti")
#: Kept: a semi join keeps the rows of this dataset that match, an anti join
#: those that do not, and neither brings the other dataset's columns. Unlike
#: the other kinds, which keep pandas' habit of matching an empty key with an
#: empty key, these follow SQL: an empty key matches nothing (E1).
FILTERING_JOINS = ("semi", "anti")


def _validate_config(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    config = ensure_config_keys(
        config,
        required={"right_dataset_id"},
        optional={"how", "suffix", "select_right_columns", "left_on", "right_on"},
    )

    right_dataset_id = config["right_dataset_id"]
    if not isinstance(right_dataset_id, str) or not right_dataset_id.strip():
        raise BadRequestError("config.right_dataset_id must be a non-empty string.")
    try:
        uuid.UUID(right_dataset_id.strip())
    except ValueError as exc:
        raise BadRequestError("config.right_dataset_id must be a valid dataset id.") from exc

    how = str(config.get("how", "inner")).lower()
    if how not in SUPPORTED_JOIN_TYPES:
        raise BadRequestError(f"config.how must be one of: {', '.join(SUPPORTED_JOIN_TYPES)}.")
    if how == "full":
        how = "outer"

    if how == "cross":
        # Every row with every row: no columns to match on.
        left_on = require_string_list(config.get("left_on") or [], field_name="config.left_on", allow_empty=True)
        right_on = require_string_list(config.get("right_on") or [], field_name="config.right_on", allow_empty=True)
        if left_on or right_on:
            raise BadRequestError("A cross join pairs every row with every row, so it matches on no columns.")
    else:
        left_on = require_string_list(config.get("left_on"), field_name="config.left_on")
        right_on = require_string_list(config.get("right_on"), field_name="config.right_on")
    if len(left_on) != len(right_on):
        raise BadRequestError("config.left_on and config.right_on must have the same number of columns.")
    ensure_columns_exist(dataframe, left_on, field_name="config.left_on")

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

    if settings["how"] in FILTERING_JOINS:
        keys = right[settings["right_on"]].dropna().drop_duplicates()
        keys.columns = settings["left_on"]
        found = dataframe.reset_index(drop=True).merge(keys, how="left", on=settings["left_on"], indicator=True)
        matched = (found["_merge"] == "both").to_numpy()
        matched &= ~dataframe[settings["left_on"]].isna().any(axis=1).to_numpy()
        kept = dataframe.reset_index(drop=True)[matched if settings["how"] == "semi" else ~matched]
        if left_rows and kept.empty:
            warnings.append(f"No rows {'matched' if settings['how'] == 'semi' else 'were missing from'} '{label}'.")
        return kept.reset_index(drop=True), warnings

    # Counted exactly before the join is built, against the row cap and the
    # run's memory ceiling (D2). This estimated from duplicate counts before,
    # and 30,000 rows matching 30,000 on one key passed it.
    check_join(dataframe, right, settings["left_on"], settings["right_on"], settings["how"],
               max_rows=MAX_JOIN_RESULT_ROWS)
    left_key_dupes = int(dataframe.duplicated(subset=settings["left_on"]).sum()) if settings["left_on"] else 0
    right_key_dupes = int(right.duplicated(subset=settings["right_on"]).sum()) if settings["right_on"] else 0
    if left_key_dupes and right_key_dupes:
        warnings.append(
            "Join keys are non-unique on both sides, so matching rows are multiplied (many-to-many)."
        )

    try:
        if settings["how"] == "cross":
            merged = dataframe.merge(right, how="cross", suffixes=("", settings["suffix"]))
        else:
            merged = dataframe.merge(
                right,
                how=settings["how"],
                left_on=settings["left_on"],
                right_on=settings["right_on"],
                suffixes=("", settings["suffix"]),
            )
    except ValueError as exc:
        raise BadRequestError(f"Join failed: {exc}") from exc

    if merged.empty and left_rows and right_rows:
        warnings.append(f"Join with '{label}' matched no rows; check that the key columns line up.")
    elif settings["how"] == "inner" and len(merged) < left_rows:
        warnings.append(
            f"Inner join dropped {count_of(left_rows - len(merged), 'unmatched row')} from the left dataset."
        )

    return merged.reset_index(drop=True), warnings
