"""The pandas side of the `Window` node.

Every function here follows SQL's rules, because the ones that push down have
to give the same numbers in a database: an empty value is skipped by an
aggregate and an aggregate over nothing is empty, an empty partition key is a
partition of its own, a lag's default applies past the partition's edge and
never to a value that is itself empty, and rows that tie on the ordering are
*peers*, which a frame counted in peers takes together.

The rows keep their order. Each partition is put in order once, the values are
computed along it, and the answers go back to the rows they belong to.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from service_transformations.ir.expressions import Expr, Literal
from service_transformations.ir.nodes import IRError, Window, WindowCall


def run_window(node: Window, frame: pd.DataFrame, evaluate: Callable[[Expr, pd.DataFrame], pd.Series]) -> pd.DataFrame:
    frame = frame.reset_index(drop=True)
    out = frame.copy()
    rows = len(frame)
    if rows == 0:
        for name, _ in node.functions:
            out[name] = pd.Series(dtype="object")
        return out

    order = _ordering(node, frame, evaluate)
    shape = _Shape.of(node, frame, order, evaluate)
    declared = node.schema()
    for name, call in node.functions:
        values = np.asarray(_compute(call, shape, frame, order, evaluate))
        placed = np.empty(rows, dtype=object) if values.dtype == object else np.empty(rows, dtype=values.dtype)
        placed[order] = values
        column = _tidy(placed)
        if declared[name].is_integer and pd.api.types.is_float_dtype(column):
            # A total of whole numbers is a whole number, as SQL says; pandas
            # carried it as a float because a frame can be empty.
            column = column.round().astype("Int64")
        out[name] = column
    return out


# ------------------------------------------------------------------ ordering


def _ordering(node: Window, frame: pd.DataFrame, evaluate) -> np.ndarray:
    """Row positions in partition order, then the window's order, stable."""
    sorter = pd.DataFrame(index=frame.index)
    columns: list[str] = []
    ascending: list[bool] = []
    if node.partition_by:
        sorter["__partition"] = frame.groupby(list(node.partition_by), dropna=False, sort=False).ngroup()
        columns.append("__partition")
        ascending.append(True)
    for index, key in enumerate(node.order_by):
        values = evaluate(key.expr, frame).reset_index(drop=True)
        empty = values.isna()
        # Nulls go where the key says, ahead of the values themselves.
        sorter[f"__null{index}"] = (~empty if key.nulls_first else empty).astype(int)
        sorter[f"__key{index}"] = _sortable(values)
        columns += [f"__null{index}", f"__key{index}"]
        ascending += [True, key.direction == "asc"]
    if not columns:
        return np.arange(len(frame))
    return sorter.sort_values(columns, ascending=ascending, kind="stable").index.to_numpy()


def _sortable(values: pd.Series) -> pd.Series:
    """A key pandas can sort: numbers, times and booleans as numbers, the rest as text."""
    if pd.api.types.is_bool_dtype(values):
        return values.astype(float)
    if pd.api.types.is_numeric_dtype(values) or pd.api.types.is_datetime64_any_dtype(values):
        return values
    present = values.dropna()
    if len(present) and present.map(lambda v: isinstance(v, (int, float, np.number)) and not isinstance(v, bool)).all():
        return pd.to_numeric(values, errors="coerce")
    return values.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))


class _Shape:
    """Where each sorted row sits: its partition, its position, its peers."""

    def __init__(self, partition: np.ndarray, peer: np.ndarray) -> None:
        self.partition = partition
        self.peer = peer
        rows = len(partition)
        self.position = pd.Series(np.ones(rows, dtype=np.int64)).groupby(partition).cumsum().to_numpy() - 1
        sizes = pd.Series(partition).map(pd.Series(partition).value_counts()).to_numpy()
        self.size = sizes.astype(np.int64)
        self.start = np.arange(rows) - self.position
        peer_series = pd.Series(np.arange(rows)).groupby(peer)
        self.peer_first = peer_series.transform("min").to_numpy()
        self.peer_last = peer_series.transform("max").to_numpy()

    @classmethod
    def of(cls, node: Window, frame: pd.DataFrame, order: np.ndarray, evaluate) -> "_Shape":
        rows = len(order)
        if node.partition_by:
            ids = frame.groupby(list(node.partition_by), dropna=False, sort=False).ngroup().to_numpy()[order]
        else:
            ids = np.zeros(rows, dtype=np.int64)
        change = np.ones(rows, dtype=bool)
        change[1:] = ids[1:] != ids[:-1]
        for key in node.order_by:
            values = _sortable(evaluate(key.expr, frame).reset_index(drop=True)).to_numpy()[order]
            change[1:] |= ~_same(values[1:], values[:-1])
        peer = np.cumsum(change)
        return cls(ids, peer)


def _same(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Element-wise equality where two empty values are the same."""
    left_empty = pd.isna(left)
    right_empty = pd.isna(right)
    with np.errstate(invalid="ignore"):
        equal = np.asarray(left == right, dtype=bool) & ~left_empty & ~right_empty
    return equal | (left_empty & right_empty)


# ------------------------------------------------------------------ functions


def _compute(call: WindowCall, shape: _Shape, frame: pd.DataFrame, order: np.ndarray, evaluate) -> np.ndarray:
    name = call.function
    constants = [arg.value for arg in call.args if isinstance(arg, Literal)]

    def value(index: int = 0) -> pd.Series:
        return evaluate(call.args[index], frame).reset_index(drop=True).iloc[order].reset_index(drop=True)

    if name == "row_number":
        return shape.position + 1
    if name == "rank":
        return shape.peer_first - shape.start + 1
    if name == "dense_rank":
        new_peer = np.ones(len(order), dtype=np.int64)
        new_peer[1:] = (shape.peer[1:] != shape.peer[:-1]).astype(np.int64)
        new_peer[shape.position == 0] = 1
        return pd.Series(new_peer).groupby(shape.partition).cumsum().to_numpy()
    if name == "percent_rank":
        rank = shape.peer_first - shape.start + 1
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(shape.size > 1, (rank - 1) / np.maximum(shape.size - 1, 1), 0.0)
        return result.astype(float)
    if name == "cume_dist":
        return ((shape.peer_last - shape.start + 1) / shape.size).astype(float)
    if name == "ntile":
        buckets = int(constants[0])
        if buckets < 1:
            raise IRError("ntile needs at least one bucket.")
        quotient, remainder = shape.size // buckets, shape.size % buckets
        big = remainder * (quotient + 1)
        position = shape.position
        with np.errstate(divide="ignore", invalid="ignore"):
            small = np.where(quotient > 0, remainder + (position - big) // np.maximum(quotient, 1) + 1, 0)
        return np.where(position < big, position // (quotient + 1) + 1, small).astype(np.int64)
    if name in ("lag", "lead"):
        return _offset(name, value(), call, shape)
    if name in ("first_value", "last_value", "nth_value"):
        return _value_at(name, value(), call, shape)
    if name in ("sum", "avg", "min", "max", "count", "product", "stddev"):
        return _framed_aggregate(name, value(), call, shape)
    if name == "ema":
        span = float(constants[0])
        if span < 1:
            raise IRError("An exponential average needs a span of at least 1.")
        numbers = pd.to_numeric(value(), errors="coerce")
        smoothed = numbers.groupby(shape.partition).transform(
            lambda part: part.ewm(span=span, adjust=False, ignore_na=True).mean())
        return smoothed.to_numpy(dtype=float)
    if name == "rolling_corr":
        rows = int(constants[0])
        if rows < 2:
            raise IRError("A rolling correlation needs at least 2 rows.")
        left = pd.to_numeric(value(0), errors="coerce")
        right = pd.to_numeric(value(1), errors="coerce")
        result = np.full(len(order), np.nan)
        for partition in np.unique(shape.partition):
            where = np.flatnonzero(shape.partition == partition)
            result[where] = left.iloc[where].rolling(rows, min_periods=2).corr(right.iloc[where]).to_numpy()
        return result
    if name == "session":
        gap = float(constants[0])
        times = value()
        if not pd.api.types.is_datetime64_any_dtype(times) and not pd.api.types.is_numeric_dtype(times):
            times = pd.to_datetime(times, errors="coerce", format="mixed")
        if pd.api.types.is_datetime64_any_dtype(times):
            seconds = times.astype("int64").astype(float) / 1e9
            seconds[times.isna().to_numpy()] = np.nan
        else:
            seconds = pd.to_numeric(times, errors="coerce").astype(float)
        previous = seconds.groupby(shape.partition).shift(1)
        starts = (shape.position == 0) | ((seconds - previous) > gap).to_numpy() | previous.isna().to_numpy()
        numbered = pd.Series(starts.astype(np.int64)).groupby(shape.partition).cumsum().to_numpy().astype(object)
        numbered[seconds.isna().to_numpy()] = None
        return numbered
    if name == "fill_forward":
        return value().groupby(shape.partition).ffill().to_numpy(dtype=object)
    if name == "fill_backward":
        return value().groupby(shape.partition).bfill().to_numpy(dtype=object)
    raise IRError(f"No pandas implementation for window function {name!r}.")  # pragma: no cover


def _offset(name: str, values: pd.Series, call: WindowCall, shape: _Shape) -> np.ndarray:
    offset = int(call.args[1].value) if len(call.args) > 1 else 1
    default = call.args[2].value if len(call.args) > 2 else None
    if offset < 0:
        raise IRError(f"{name} needs an offset of 0 or more.")
    steps = offset if name == "lag" else -offset
    shifted = values.groupby(shape.partition).shift(steps).to_numpy(dtype=object)
    inside = shape.position >= offset if name == "lag" else shape.position < shape.size - offset
    return np.where(inside, shifted, default)


def _value_at(name: str, values: pd.Series, call: WindowCall, shape: _Shape) -> np.ndarray:
    data = values.to_numpy(dtype=object)
    rows = len(data)
    frame = call.frame
    index = np.arange(rows)
    # The frame's first and last row positions, per row.
    if frame.whole:
        low, high = shape.start, shape.start + shape.size - 1
    elif frame.unit == "peers":
        low, high = shape.start, shape.peer_last
    else:
        low = shape.start if frame.start is None else np.maximum(shape.start, index - frame.start)
        high = index
    if name == "first_value":
        return data[low]
    if name == "last_value":
        return data[high]
    nth = int(call.args[1].value)
    if nth < 1:
        raise IRError("nth value counts from 1.")
    target = low + nth - 1
    return np.where(target <= high, data[np.minimum(target, rows - 1)], None)


def _framed_aggregate(name: str, values: pd.Series, call: WindowCall, shape: _Shape) -> np.ndarray:
    frame = call.frame
    numeric = name in ("sum", "avg", "product", "stddev")
    series = pd.to_numeric(values, errors="coerce") if numeric else values
    times = False
    zone = getattr(values.dt, "tz", None) if pd.api.types.is_datetime64_any_dtype(values) else None
    if name in ("min", "max"):
        series, times = _comparable(series, whole=frame.whole)
    groups = series.groupby(shape.partition)
    result = _framed(name, series, groups, frame, shape)
    if times:
        stamps = pd.to_datetime(pd.Series(result), unit="ns")
        return (stamps.dt.tz_localize("UTC").dt.tz_convert(zone) if zone is not None else stamps).to_numpy(dtype=object)
    return result


def _comparable(series: pd.Series, *, whole: bool) -> tuple[pd.Series, bool]:
    """Lowest and highest compare numbers and times; over a whole partition, text too."""
    if pd.api.types.is_datetime64_any_dtype(series):
        stamps = series.dt.tz_localize(None) if getattr(series.dt, "tz", None) is not None else series
        numbers = stamps.astype("int64").astype(float)
        numbers[series.isna().to_numpy()] = np.nan
        return numbers, True
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series, False
    converted = pd.to_numeric(series, errors="coerce")
    if converted.notna().sum() == series.notna().sum():
        return converted, False
    if whole:
        return series, False
    raise IRError("A running lowest or highest value works on numbers and dates.")


def _framed(name: str, series: pd.Series, groups, frame, shape: _Shape) -> np.ndarray:

    if frame.whole:
        if name == "sum":
            return groups.transform("sum", min_count=1).to_numpy()
        if name == "product":
            return groups.transform("prod", min_count=1).to_numpy()
        if name == "stddev":
            return groups.transform("std").to_numpy()
        method = {"avg": "mean", "min": "min", "max": "max", "count": "count"}[name]
        return groups.transform(method).to_numpy()

    if frame.start is not None:
        size = frame.start + 1
        rolled = groups.rolling(size, min_periods=1)
        if name == "count":
            result = series.notna().astype(float).groupby(shape.partition).rolling(size, min_periods=1).sum()
        elif name == "product":
            result = rolled.apply(_product, raw=True)
        else:
            result = getattr(rolled, {"sum": "sum", "avg": "mean", "min": "min", "max": "max", "stddev": "std"}[name])()
        result = result.reset_index(level=0, drop=True).sort_index().to_numpy()
        if name == "count":
            result = result.astype(np.int64)
        return result

    # From the start of the partition to the current row, then over peers.
    present = series.notna()
    counted = present.astype(np.int64).groupby(shape.partition).cumsum().to_numpy()
    if name == "count":
        running = counted
    elif name in ("sum", "avg"):
        totals = series.fillna(0).groupby(shape.partition).cumsum().to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            running = np.where(counted > 0, totals / (np.maximum(counted, 1) if name == "avg" else 1), np.nan)
    elif name == "product":
        products = series.fillna(1).groupby(shape.partition).cumprod().to_numpy(dtype=float)
        running = np.where(counted > 0, products, np.nan)
    elif name == "stddev":
        running = groups.expanding(min_periods=1).std().reset_index(level=0, drop=True).sort_index().to_numpy()
    else:
        cumulative = getattr(groups, "cummin" if name == "min" else "cummax")()
        running = cumulative.groupby(shape.partition).ffill().to_numpy()
    if frame.unit == "peers":
        running = running[shape.peer_last]
    return running


def _product(window: np.ndarray) -> float:
    present = window[~np.isnan(window)]
    return float(np.prod(present)) if len(present) else np.nan


def _tidy(values: np.ndarray) -> pd.Series:
    """A column pandas types sensibly: numbers as numbers, the rest as given."""
    series = pd.Series(values)
    if series.dtype == object:
        present = series.dropna()
        if len(present) and present.map(lambda v: isinstance(v, (bool, np.bool_))).all():
            return series.astype("boolean")
        inferred = series.infer_objects()
        if inferred.dtype != object:
            return inferred
    return series


def literal_value(arg: Any) -> Any:
    return arg.value if isinstance(arg, Literal) else None
