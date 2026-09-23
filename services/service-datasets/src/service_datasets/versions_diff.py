"""Diffing two dataset versions (Phase 18, decision #7).

The rule this module exists to enforce: **changed-row and per-cell
classification require trustworthy identity.** With caller-supplied identity
columns that are unique in both snapshots, rows can be matched and compared.
Without them, the diff returns duplicate-aware added/removed multisets and says
plainly that changed-classification is unavailable — it never guesses which
removed row "became" which added row.

Values are compared as strings. That is deliberate and stated in the response's
`method`: two versions may round-trip through CSV, where `1` and `1.0` are
different texts for what may or may not be the same fact — a diff that
pretended to know better would be inventing type information the artifact does
not carry.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

#: Sample rows returned per bucket. Counts are always exact; samples are a
#: window, and the cap is declared in the response rather than silently applied.
SAMPLE_LIMIT = 20

METHOD = "string-compared rows; identity match when unique identity columns are supplied"


def _records(frame: pd.DataFrame, limit: int = SAMPLE_LIMIT) -> list[dict[str, Any]]:
    """JSON-safe sample records: every value as text, nulls as None."""
    out: list[dict[str, Any]] = []
    for _, row in frame.head(limit).iterrows():
        out.append(
            {
                str(column): (None if pd.isna(value) else str(value))
                for column, value in row.items()
            }
        )
    return out


def _row_counter(frame: pd.DataFrame) -> Counter:
    strs = frame.astype(str).where(~frame.isna(), None)
    return Counter(tuple(row) for row in strs.itertuples(index=False, name=None))


def diff_frames(
    before: pd.DataFrame,
    after: pd.DataFrame,
    identity_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Compare two snapshots of one logical dataset.

    Returns a dict matching the DatasetVersionDiff schema fields (minus the
    version bookkeeping the service layer adds).
    """
    before_cols = [str(c) for c in before.columns]
    after_cols = [str(c) for c in after.columns]
    columns_added = [c for c in after_cols if c not in before_cols]
    columns_removed = [c for c in before_cols if c not in after_cols]

    result: dict[str, Any] = {
        "rows_before": int(len(before)),
        "rows_after": int(len(after)),
        "columns_added": columns_added,
        "columns_removed": columns_removed,
        "sample_limit": SAMPLE_LIMIT,
        "method": METHOD,
    }

    identity = [c.strip() for c in (identity_columns or []) if c.strip()]
    if identity:
        missing = [c for c in identity if c not in before_cols or c not in after_cols]
        if missing:
            raise BadRequestError(
                f"Identity column(s) {', '.join(missing)} are not present in both versions."
            )
        before_keys = before[identity].astype(str)
        after_keys = after[identity].astype(str)
        if before_keys.duplicated().any() or after_keys.duplicated().any():
            # Decision #7: a non-unique key is not identity. Fall back to the
            # multiset answer and say why, rather than matching arbitrarily.
            result.update(_multiset_diff(before, after))
            result["changed_available"] = False
            result["reason"] = (
                "The supplied identity columns are not unique in both versions, "
                "so rows cannot be matched; added/removed are duplicate-aware "
                "multiset counts."
            )
            return result

        result.update(_identity_diff(before, after, identity))
        result["changed_available"] = True
        result["reason"] = None
        return result

    result.update(_multiset_diff(before, after))
    result["changed_available"] = False
    result["reason"] = (
        "No identity columns were supplied, so rows cannot be matched; "
        "added/removed are duplicate-aware multiset counts and "
        "changed-row classification is unavailable."
    )
    return result


def _multiset_diff(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, Any]:
    """Duplicate-aware added/removed. A row present twice before and once after
    counts as one removal — Counter arithmetic, not set arithmetic."""
    same_shape = list(before.columns.astype(str)) == list(after.columns.astype(str))
    if not same_shape:
        # With different column sets, no row of one version can equal a row of
        # the other; every row is added or removed. Exact and honest.
        return {
            "rows_added": int(len(after)),
            "rows_removed": int(len(before)),
            "rows_changed": None,
            "sample_added": _records(after),
            "sample_removed": _records(before),
            "sample_changed": [],
        }

    before_counts = _row_counter(before)
    after_counts = _row_counter(after)
    added = after_counts - before_counts
    removed = before_counts - after_counts
    columns = [str(c) for c in after.columns]

    def _sample(counter: Counter) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for values, count in counter.items():
            for _ in range(count):
                rows.append(dict(zip(columns, values)))
                if len(rows) >= SAMPLE_LIMIT:
                    return rows
        return rows

    return {
        "rows_added": int(sum(added.values())),
        "rows_removed": int(sum(removed.values())),
        "rows_changed": None,
        "sample_added": _sample(added),
        "sample_removed": _sample(removed),
        "sample_changed": [],
    }


def _identity_diff(
    before: pd.DataFrame, after: pd.DataFrame, identity: list[str]
) -> dict[str, Any]:
    """Row classification against a trustworthy key: added, removed, changed."""
    before_i = before.copy()
    after_i = after.copy()
    before_i.index = pd.MultiIndex.from_frame(before[identity].astype(str))
    after_i.index = pd.MultiIndex.from_frame(after[identity].astype(str))

    before_keys = set(before_i.index)
    after_keys = set(after_i.index)
    added_keys = after_keys - before_keys
    removed_keys = before_keys - after_keys
    common_keys = before_keys & after_keys

    common_columns = [
        c for c in before.columns.astype(str) if c in set(after.columns.astype(str))
    ]
    compare_columns = [c for c in common_columns if c not in identity]

    changed_rows: list[dict[str, Any]] = []
    changed_count = 0
    cells_by_column: Counter = Counter()
    if compare_columns and common_keys:
        left = before_i.loc[sorted(common_keys), compare_columns].astype(str)
        right = after_i.loc[sorted(common_keys), compare_columns].astype(str)
        unequal = left != right
        row_changed = unequal.any(axis=1)
        changed_count = int(row_changed.sum())
        for column in compare_columns:
            count = int(unequal[column].sum())
            if count:
                cells_by_column[column] = count
        for key in right.index[row_changed][:SAMPLE_LIMIT]:
            entry: dict[str, Any] = dict(zip(identity, key))
            for column in compare_columns:
                if left.at[key, column] != right.at[key, column]:
                    entry[column] = {
                        "before": left.at[key, column],
                        "after": right.at[key, column],
                    }
            changed_rows.append(entry)

    return {
        "rows_added": len(added_keys),
        "rows_removed": len(removed_keys),
        "rows_changed": changed_count,
        "sample_added": _records(after_i.loc[sorted(added_keys)]) if added_keys else [],
        "sample_removed": _records(before_i.loc[sorted(removed_keys)]) if removed_keys else [],
        "sample_changed": changed_rows,
        "cells_changed_by_column": dict(cells_by_column),
    }
