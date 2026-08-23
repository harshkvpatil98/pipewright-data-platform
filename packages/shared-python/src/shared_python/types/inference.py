"""Infer a canonical type from actual values.

The existing ``infer_series_type`` answers with one of seven bare strings and is
consumed in two dozen places. This does the same job into the lattice, where the
answer can carry precision, timezone awareness and exactness -- and, critically,
can say ``UNKNOWN`` instead of guessing.

The two live side by side: :func:`to_legacy_name` maps back, and a differential
test asserts the two agree, so the old callers keep working while new code moves
to the richer answer.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_module
from decimal import Decimal

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_float_dtype,
    is_integer_dtype,
    is_object_dtype,
    is_string_dtype,
    is_timedelta64_dtype,
)

from shared_python.types.lattice import (
    BOOLEAN,
    BYTES,
    DATE,
    FLOAT32,
    FLOAT64,
    INT8,
    INT16,
    INT32,
    INT64,
    INTERVAL,
    JSON,
    STRING,
    UINT8,
    UINT16,
    UINT32,
    UINT64,
    UNKNOWN,
    UUID,
    Kind,
    PWType,
    decimal,
    time,
    timestamp,
)

#: How many values to look at in an object column. Object dtype has no declared
#: type, so the only way to know is to look -- but looking at 50 million rows to
#: type a column is not a trade anyone would take.
DEFAULT_SAMPLE = 10_000

_NUMPY_INTS = {
    "int8": INT8, "int16": INT16, "int32": INT32, "int64": INT64,
    "uint8": UINT8, "uint16": UINT16, "uint32": UINT32, "uint64": UINT64,
    "Int8": INT8, "Int16": INT16, "Int32": INT32, "Int64": INT64,
    "UInt8": UINT8, "UInt16": UINT16, "UInt32": UINT32, "UInt64": UINT64,
}


def infer_pw_type(series: pd.Series, *, sample: int = DEFAULT_SAMPLE) -> PWType:
    """The canonical type of a column, or UNKNOWN when it cannot be determined."""
    non_null = series.dropna()
    nullable = bool(series.isna().any()) or len(non_null) < len(series)

    if non_null.empty:
        # An empty column is genuinely untyped. Calling it a string is a guess
        # that the next load will contradict.
        return UNKNOWN

    dtype_name = str(series.dtype)

    if is_bool_dtype(series):
        return BOOLEAN.with_nullable(nullable)
    if dtype_name in _NUMPY_INTS:
        return _NUMPY_INTS[dtype_name].with_nullable(nullable)
    if is_integer_dtype(series):
        return INT64.with_nullable(nullable)
    if is_float_dtype(series):
        return (FLOAT32 if dtype_name.endswith("32") else FLOAT64).with_nullable(nullable)
    if is_timedelta64_dtype(series):
        return INTERVAL.with_nullable(nullable)
    if is_datetime64_any_dtype(series):
        tz_aware = getattr(series.dtype, "tz", None) is not None
        unit = {"s": 0, "ms": 3, "us": 6, "ns": 9}.get(
            getattr(series.dtype, "unit", "ns"), 9
        )
        return timestamp(tz_aware=tz_aware, precision=unit).with_nullable(nullable)
    if is_string_dtype(series) and not is_object_dtype(series):
        return STRING.with_nullable(nullable)

    if is_object_dtype(series):
        return _infer_object(non_null, sample=sample).with_nullable(nullable)

    return UNKNOWN


def _infer_object(non_null: pd.Series, *, sample: int) -> PWType:
    """Type an object column by looking at what is actually in it."""
    values = non_null.head(sample)
    types = {type(value) for value in values}

    if types <= {bool}:
        return BOOLEAN
    if types <= {Decimal}:
        return _decimal_covering(values)
    if types <= {str}:
        return STRING
    if types <= {bytes, bytearray}:
        return BYTES
    if types <= {uuid_module.UUID}:
        return UUID
    if types <= {dict, list}:
        return JSON
    if types <= {int}:
        return _int_covering(values)
    if types <= {int, float}:
        return FLOAT64
    if types <= {int, Decimal} or types <= {Decimal, float}:
        # Mixed exact and inexact numerics: the exact side wins, because
        # widening to float would silently discard the exactness.
        return _decimal_covering([v for v in values if isinstance(v, Decimal)])
    if types <= {dt.date} or types <= {dt.date, dt.datetime}:
        if all(type(v) is dt.date for v in values):
            return DATE
        return timestamp(tz_aware=_all_aware(values))
    if types <= {dt.datetime, pd.Timestamp}:
        return timestamp(tz_aware=_all_aware(values))
    if types <= {dt.time}:
        return time()

    # Genuinely mixed. Naming it STRING would let a numeric column with one bad
    # row become text for everything downstream.
    return UNKNOWN


def _all_aware(values) -> bool:
    return all(getattr(v, "tzinfo", None) is not None for v in values)


def _decimal_covering(values) -> PWType:
    """The narrowest DECIMAL that holds every value exactly."""
    max_scale = 0
    max_whole = 1
    for value in values:
        sign, digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):  # NaN / Infinity
            return UNKNOWN
        scale = max(0, -exponent)
        whole = max(1, len(digits) - scale)
        max_scale = max(max_scale, scale)
        max_whole = max(max_whole, whole)
    return decimal(max_whole + max_scale, max_scale)


def _int_covering(values) -> PWType:
    """The narrowest integer kind holding every value, defaulting to INT64."""
    low = min(values)
    high = max(values)
    for candidate in (INT8, UINT8, INT16, UINT16, INT32, UINT32, INT64, UINT64):
        from shared_python.types.lattice import INT_RANGE

        bound_low, bound_high = INT_RANGE[candidate.kind]
        if bound_low <= low and high <= bound_high:
            return candidate
    # Beyond 64 bits: exact decimal rather than an overflowing integer.
    return decimal(len(str(max(abs(low), abs(high)))), 0)


#: The legacy vocabulary is NOT the seven words it looks like. For an object
#: column the original implementation returns the lowercased Python type name,
#: so "decimal", "uuid", "date", "time", "bytes", "dict" and "list" all occur.
#: Anything downstream switching on `inferred_type` is switching on an open set.
#: Reproduced faithfully here so the bridge does not change existing answers.
_LEGACY_BY_KIND = {
    Kind.BOOLEAN: "boolean",
    Kind.FLOAT32: "float", Kind.FLOAT64: "float",
    Kind.DECIMAL: "decimal",
    Kind.STRING: "string",
    Kind.UUID: "uuid",
    Kind.BYTES: "bytes",
    Kind.DATE: "date",
    Kind.TIME: "time",
    Kind.TIMESTAMP: "datetime",
    Kind.INTERVAL: "timedelta",
    Kind.GEOGRAPHY: "string",
    Kind.ARRAY: "list",
    Kind.STRUCT: "dict",
    Kind.MAP: "dict",
}


def to_legacy_name(type_: PWType, *, was_empty: bool = False) -> str:
    """Render a canonical type in the vocabulary the old callers speak.

    Faithful for every case except JSON: the lattice has one JSON kind while the
    original returns "dict" or "list" depending on what the column held, and a
    type alone cannot recover which. Callers needing that distinction should
    keep using ``infer_series_type`` directly.
    """
    if was_empty:
        return "empty"
    if type_.kind is Kind.UNKNOWN:
        return "mixed"
    if type_.is_integer:
        return "int"
    if type_.kind is Kind.JSON:
        return "dict"
    return _LEGACY_BY_KIND.get(type_.kind, "string")
