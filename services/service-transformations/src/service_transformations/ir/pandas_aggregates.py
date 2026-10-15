"""Every aggregate, once: what a group of rows comes to.

The IR's pandas backend and the aggregate step both call this, so a median, a
percentile or a weighted average means one thing wherever it is computed, and
the ones that lower to SQL are proven against databases in
`test_aggregates.py`. SQL's rules hold: an empty value is skipped, and a group
with no values at all comes to nothing (a total of nothing is empty, not 0;
a count of nothing is 0).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from service_transformations.ir.nodes import IRError

#: Functions pandas has under another name.
_METHODS = {
    "avg": "mean", "min": "min", "max": "max", "median": "median", "count": "count",
    "count_distinct": "nunique", "stddev": "std", "variance": "var", "first": "first", "last": "last",
}

#: Aggregates that read numbers; anything else in the column is no value.
NUMERIC = frozenset({"sum", "avg", "median", "stddev", "variance", "product", "percentile", "range",
                     "corr", "covar", "weighted_avg"})


def aggregate(working: pd.DataFrame, keys: list[str], function: str, columns: list[str],
              constants: list[Any]) -> Any:
    """`function` over `columns` of `working`, per group of `keys`.

    With keys, a Series indexed the way ``groupby(keys, dropna=False, sort=True)``
    indexes its groups; without, one value.
    """
    import warnings

    with warnings.catch_warnings(), np.errstate(divide="ignore", invalid="ignore"):
        # A spread or a correlation of one value has no answer, which numpy
        # says with a warning and gives as empty; empty is the answer.
        warnings.simplefilter("ignore", RuntimeWarning)
        return _aggregate(working, keys, function, columns, constants)


def _aggregate(working: pd.DataFrame, keys: list[str], function: str, columns: list[str],
               constants: list[Any]) -> Any:
    frame = working
    if function in NUMERIC:
        frame = working.copy()
        for column in columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    value = columns[0] if columns else None

    def by(series: pd.Series):
        return series.groupby([frame[key] for key in keys], dropna=False, sort=True) if keys else None

    def each(fn):
        """`fn(values)` per group, or over everything."""
        if keys:
            return frame.groupby(keys, dropna=False, sort=True)[value].agg(fn)
        return fn(frame[value])

    def pairs(fn):
        """`fn(x, y)` per group over two columns."""
        if keys:
            return frame.groupby(keys, dropna=False, sort=True)[columns].apply(
                lambda part: fn(part[columns[0]], part[columns[1]]))
        return fn(frame[columns[0]], frame[columns[1]])

    if function == "sum":
        return by(frame[value]).sum(min_count=1) if keys else frame[value].sum(min_count=1)
    if function == "product":
        return by(frame[value]).prod(min_count=1) if keys else frame[value].prod(min_count=1)
    if function == "count" and value is None:
        return frame.groupby(keys, dropna=False, sort=True).size() if keys else len(frame)
    if function in _METHODS:
        if keys:
            return getattr(frame.groupby(keys, dropna=False, sort=True)[value], _METHODS[function])()
        return getattr(frame[value], _METHODS[function])()
    if function == "count_null":
        empty = frame[value].isna().astype(np.int64)
        return by(empty).sum() if keys else int(empty.sum())
    if function == "range":
        if keys:
            grouped = frame.groupby(keys, dropna=False, sort=True)[value]
            return grouped.max() - grouped.min()
        return frame[value].max() - frame[value].min()
    if function == "percentile":
        share = float(constants[0])
        if not 0 <= share <= 1:
            raise IRError("A percentile is between 0 and 100.")
        return by(frame[value]).quantile(share) if keys else frame[value].quantile(share)
    if function in ("any_true", "all_true"):
        return each(lambda values: _truth(values, function == "any_true"))
    if function == "mode":
        return each(_mode)
    if function == "nth":
        position = int(constants[0])
        if position < 1:
            raise IRError("The nth value counts from 1.")
        return each(lambda values: _plain(values.iloc[position - 1]) if len(values) >= position else None)
    if function == "list_agg":
        return each(_listed)
    if function == "string_agg":
        separator = str(constants[0]) if constants else ", "
        return each(lambda values: separator.join(str(_plain(v)) for v in values if not pd.isna(v)) or None
                    if values.notna().any() else None)
    if function == "corr":
        return pairs(lambda x, y: x.corr(y))
    if function == "covar":
        return pairs(lambda x, y: x.cov(y))
    if function == "weighted_avg":
        x, w = frame[columns[0]], frame[columns[1]]
        both = x.notna() & w.notna()
        numerator, denominator = (x * w).where(both), w.where(both)
        if keys:
            top, bottom = by(numerator).sum(min_count=1), by(denominator).sum(min_count=1)
            return top / bottom.where(bottom != 0)
        bottom = denominator.sum(min_count=1)
        return numerator.sum(min_count=1) / bottom if bottom not in (0, None) and not pd.isna(bottom) else np.nan
    raise IRError(f"No pandas implementation for aggregate {function!r}.")


def _truth(values: pd.Series, any_: bool) -> Any:
    present = values.dropna()
    if present.empty:
        return None
    flags = present.map(lambda v: str(v).strip().lower() in ("true", "1", "yes", "t", "y")
                        if isinstance(v, str) else bool(v))
    return bool(flags.any() if any_ else flags.all())


def _mode(values: pd.Series) -> Any:
    """The commonest value; when several are as common, the smallest, so the answer never depends on order."""
    present = values.dropna()
    if present.empty:
        return None
    counts = present.value_counts()
    top = counts[counts == counts.max()].index.tolist()
    try:
        return _plain(sorted(top)[0])
    except TypeError:  # values that do not compare, such as numbers and text together
        return _plain(sorted(top, key=str)[0])


def _listed(values: pd.Series) -> Any:
    kept = [_plain(value) for value in values if not pd.isna(value)]
    # As the collect tool: a group with no values is empty, not "[]".
    return json.dumps(kept, default=str) if kept else None


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value
