"""Incremental load strategies: watermark filtering and key-based merging.

Three load modes are supported:

``full_refresh``
    Replace the target dataset with whatever the query returns.
``incremental_append``
    Fetch only rows whose cursor column is greater than the stored watermark and
    append them to the existing dataset.
``incremental_merge``
    Same fetch, then upsert on a primary key so restated rows replace the prior
    version instead of duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from service_extraction.connectors.sql_database import quote_identifier
from shared_python.errors import BadRequestError

WATERMARK_PARAM = "pw_watermark"


@dataclass(frozen=True)
class MergeOutcome:
    dataframe: pd.DataFrame
    rows_before: int
    rows_added: int
    rows_updated: int
    warnings: list[str]


def build_incremental_query(
    connector_type: str,
    *,
    base_query: str,
    cursor_column: str,
    watermark: str | None,
) -> tuple[str, dict[str, Any]]:
    """Wrap `base_query` so only rows past the watermark are returned.

    The base query becomes a subquery, which keeps user SQL untouched (and still
    read-only validated) while the cursor predicate is bound as a parameter.
    """
    if not cursor_column or not cursor_column.strip():
        raise BadRequestError("Incremental load requires a cursor column.")

    quoted_cursor = quote_identifier(connector_type, cursor_column.strip())
    inner = base_query.rstrip().rstrip(";")

    if watermark is None:
        # First run: take everything, but keep ordering so the watermark is well defined.
        return f"SELECT * FROM ({inner}) AS pw_src ORDER BY {quoted_cursor}", {}

    statement = (
        f"SELECT * FROM ({inner}) AS pw_src "
        f"WHERE {quoted_cursor} > :{WATERMARK_PARAM} "
        f"ORDER BY {quoted_cursor}"
    )
    return statement, {WATERMARK_PARAM: watermark}


def compute_watermark(dataframe: pd.DataFrame, cursor_column: str) -> str | None:
    """Return the maximum cursor value in the batch, serialised for storage.

    Watermarks are persisted as strings so one column can hold timestamps,
    integers, or ids without a per-job type. They are passed back to the driver
    as bind parameters, which handles the comparison in the column's own type.
    """
    if dataframe.empty or cursor_column not in dataframe.columns:
        return None

    series = dataframe[cursor_column].dropna()
    if series.empty:
        return None

    maximum = series.max()
    if isinstance(maximum, pd.Timestamp):
        return maximum.isoformat()
    if isinstance(maximum, (datetime, date)):
        return maximum.isoformat()
    if hasattr(maximum, "item") and callable(maximum.item):
        try:
            return str(maximum.item())
        except (ValueError, AttributeError):
            pass
    return str(maximum)


def merge_frames(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    load_mode: str,
    primary_key_columns: list[str] | None,
) -> MergeOutcome:
    """Combine an incoming batch with the dataset's current contents."""
    warnings: list[str] = []
    rows_before = int(len(existing))

    if load_mode == "full_refresh":
        return MergeOutcome(
            dataframe=incoming.reset_index(drop=True),
            rows_before=rows_before,
            rows_added=int(len(incoming)),
            rows_updated=0,
            warnings=warnings,
        )

    if existing.empty:
        return MergeOutcome(
            dataframe=incoming.reset_index(drop=True),
            rows_before=0,
            rows_added=int(len(incoming)),
            rows_updated=0,
            warnings=warnings,
        )

    if incoming.empty:
        return MergeOutcome(
            dataframe=existing.reset_index(drop=True),
            rows_before=rows_before,
            rows_added=0,
            rows_updated=0,
            warnings=["No new rows were returned for this batch."],
        )

    missing_in_existing = [c for c in incoming.columns if c not in existing.columns]
    missing_in_incoming = [c for c in existing.columns if c not in incoming.columns]
    if missing_in_existing or missing_in_incoming:
        warnings.append(
            "Column sets differ between the stored dataset and the new batch; "
            "the union of columns is kept and missing values are null."
        )

    if load_mode == "incremental_append":
        combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
        return MergeOutcome(
            dataframe=combined,
            rows_before=rows_before,
            rows_added=int(len(incoming)),
            rows_updated=0,
            warnings=warnings,
        )

    if load_mode != "incremental_merge":
        raise BadRequestError(f"Unsupported load mode '{load_mode}'.")

    keys = [key for key in (primary_key_columns or []) if key]
    if not keys:
        raise BadRequestError("incremental_merge requires at least one primary key column.")

    missing_keys = sorted({key for key in keys if key not in incoming.columns})
    if missing_keys:
        raise BadRequestError(
            f"Primary key column(s) not present in the extracted data: {', '.join(missing_keys)}."
        )
    missing_existing_keys = sorted({key for key in keys if key not in existing.columns})
    if missing_existing_keys:
        raise BadRequestError(
            f"Primary key column(s) not present in the stored dataset: {', '.join(missing_existing_keys)}."
        )

    # Rows whose key already exists are replacements, not additions.
    existing_keys = existing[keys].apply(tuple, axis=1)
    incoming_keys = incoming[keys].apply(tuple, axis=1)
    replaced_mask = existing_keys.isin(set(incoming_keys))
    rows_updated = int(replaced_mask.sum())

    retained = existing.loc[~replaced_mask]
    combined = pd.concat([retained, incoming], ignore_index=True, sort=False)

    # A single batch can restate the same key more than once; last write wins.
    duplicate_count = int(len(combined)) - int(len(combined.drop_duplicates(subset=keys, keep="last")))
    if duplicate_count:
        combined = combined.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
        warnings.append(f"Kept the last of {duplicate_count} duplicate key(s) within the batch.")

    return MergeOutcome(
        dataframe=combined.reset_index(drop=True),
        rows_before=rows_before,
        rows_added=int(len(incoming)) - rows_updated,
        rows_updated=rows_updated,
        warnings=warnings,
    )
