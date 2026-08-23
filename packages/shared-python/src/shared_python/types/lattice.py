"""The canonical type lattice every source maps into and every destination out of.

**Why this exists.** Before it, a column's type was whatever pandas inferred,
described by one of seven bare strings: "int", "float", "string", "datetime",
"boolean", "mixed", "empty". That is fine while everything is pandas. The moment
a Postgres ``NUMERIC(38,10)`` travels through Parquet into BigQuery, or a MySQL
``DATETIME`` (no zone) meets a Snowflake ``TIMESTAMP_TZ``, silent corruption
becomes possible -- and *silent* is the operative word. This platform has
already produced that class of bug once: ``postgresql.UUID`` on SQLite gets
NUMERIC affinity, and an all-digit UUID was quietly converted to a float.

**Three decisions worth stating, because they are the point of the design:**

1. ``DECIMAL`` is never a float. Financial data is the commonest ETL payload and
   ``0.1 + 0.2 != 0.3`` is not an acceptable failure mode.
2. Timezone-awareness is part of the *type*, not a flag beside it.
   ``TIMESTAMP(tz_aware=False)`` and ``TIMESTAMP(tz_aware=True)`` are different
   types that cannot meet without an explicit conversion. This is the only way
   to stop the classic "reports shift by five hours in winter" bug.
3. ``UNKNOWN`` exists and is allowed to survive. A column nobody can type is
   reported as untyped. Guessing it into STRING is how one bad row turns a
   numeric column into text for all downstream time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Kind(str, Enum):
    """The tag of a type. Parameters live on :class:`PWType`."""

    BOOLEAN = "boolean"

    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    UINT64 = "uint64"

    FLOAT32 = "float32"
    FLOAT64 = "float64"
    DECIMAL = "decimal"

    STRING = "string"
    BYTES = "bytes"

    DATE = "date"
    TIME = "time"
    TIMESTAMP = "timestamp"
    INTERVAL = "interval"

    UUID = "uuid"
    JSON = "json"
    ARRAY = "array"
    STRUCT = "struct"
    MAP = "map"
    GEOGRAPHY = "geography"

    #: Honest about not knowing. Never produced by guessing.
    UNKNOWN = "unknown"


SIGNED_INTS = (Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64)
UNSIGNED_INTS = (Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64)
INTEGER_KINDS = SIGNED_INTS + UNSIGNED_INTS
FLOAT_KINDS = (Kind.FLOAT32, Kind.FLOAT64)
NUMERIC_KINDS = INTEGER_KINDS + FLOAT_KINDS + (Kind.DECIMAL,)
TEMPORAL_KINDS = (Kind.DATE, Kind.TIME, Kind.TIMESTAMP, Kind.INTERVAL)
NESTED_KINDS = (Kind.ARRAY, Kind.STRUCT, Kind.MAP)

#: Inclusive value range of each integer kind, used by coercion to decide
#: whether a narrowing cast can actually lose data.
INT_RANGE: dict[Kind, tuple[int, int]] = {
    Kind.INT8: (-(2**7), 2**7 - 1),
    Kind.INT16: (-(2**15), 2**15 - 1),
    Kind.INT32: (-(2**31), 2**31 - 1),
    Kind.INT64: (-(2**63), 2**63 - 1),
    Kind.UINT8: (0, 2**8 - 1),
    Kind.UINT16: (0, 2**16 - 1),
    Kind.UINT32: (0, 2**32 - 1),
    Kind.UINT64: (0, 2**64 - 1),
}

#: Digits an IEEE-754 float can carry without loss. Used to decide whether a
#: DECIMAL survives a trip through a float.
FLOAT_SIGNIFICANT_DIGITS = {Kind.FLOAT32: 7, Kind.FLOAT64: 15}

MAX_DECIMAL_PRECISION = 76  # wider than any dialect here supports


@dataclass(frozen=True)
class PWType:
    """A type in the canonical lattice.

    Deliberately narrower than "whatever a database offers": every source type
    maps *into* this set and this set maps *out* to every destination, so the
    number of conversions is 2N rather than N-squared.
    """

    kind: Kind

    #: DECIMAL only. Total significant digits, and digits after the point.
    precision: int | None = None
    scale: int | None = None

    #: STRING/BYTES only. ``None`` means unbounded.
    max_length: int | None = None

    #: TIME/TIMESTAMP only. Fractional-second digits (0-9).
    time_precision: int | None = None

    #: TIMESTAMP only. Part of the type, not a modifier: a zoned and a naive
    #: timestamp are different types.
    tz_aware: bool = False

    #: ARRAY/MAP element and value types.
    element: PWType | None = None
    key: PWType | None = None
    value: PWType | None = None

    #: STRUCT fields, in declaration order.
    fields: tuple[tuple[str, PWType], ...] = field(default_factory=tuple)

    #: Whether the column admits nulls. Not part of identity for casting
    #: purposes, but carried so a NOT NULL destination can be checked.
    nullable: bool = True

    def __post_init__(self) -> None:
        if self.kind is Kind.DECIMAL:
            if self.precision is None or self.scale is None:
                raise ValueError("DECIMAL requires both precision and scale.")
            if not 1 <= self.precision <= MAX_DECIMAL_PRECISION:
                raise ValueError(
                    f"DECIMAL precision must be 1..{MAX_DECIMAL_PRECISION}, got {self.precision}."
                )
            if not 0 <= self.scale <= self.precision:
                raise ValueError(
                    f"DECIMAL scale must be 0..precision ({self.precision}), got {self.scale}."
                )
        if self.kind is Kind.ARRAY and self.element is None:
            raise ValueError("ARRAY requires an element type.")
        if self.kind is Kind.MAP and (self.key is None or self.value is None):
            raise ValueError("MAP requires both key and value types.")
        if self.kind is Kind.STRUCT and not self.fields:
            raise ValueError("STRUCT requires at least one field.")
        if self.time_precision is not None and not 0 <= self.time_precision <= 9:
            raise ValueError("Fractional-second precision must be 0..9.")
        if self.max_length is not None and self.max_length < 1:
            raise ValueError("max_length must be at least 1.")
        if self.tz_aware and self.kind is not Kind.TIMESTAMP:
            raise ValueError("Only TIMESTAMP carries timezone awareness.")

    # -- predicates ------------------------------------------------------

    @property
    def is_integer(self) -> bool:
        return self.kind in INTEGER_KINDS

    @property
    def is_float(self) -> bool:
        return self.kind in FLOAT_KINDS

    @property
    def is_numeric(self) -> bool:
        return self.kind in NUMERIC_KINDS

    @property
    def is_temporal(self) -> bool:
        return self.kind in TEMPORAL_KINDS

    @property
    def is_nested(self) -> bool:
        return self.kind in NESTED_KINDS

    @property
    def is_signed(self) -> bool:
        return self.kind in SIGNED_INTS

    @property
    def is_known(self) -> bool:
        return self.kind is not Kind.UNKNOWN

    def with_nullable(self, nullable: bool) -> PWType:
        return replace_nullable(self, nullable)

    # -- rendering -------------------------------------------------------

    def __str__(self) -> str:
        if self.kind is Kind.DECIMAL:
            return f"decimal({self.precision},{self.scale})"
        if self.kind is Kind.STRING and self.max_length is not None:
            return f"string({self.max_length})"
        if self.kind is Kind.BYTES and self.max_length is not None:
            return f"bytes({self.max_length})"
        if self.kind is Kind.TIMESTAMP:
            zone = "tz" if self.tz_aware else "naive"
            if self.time_precision is not None:
                return f"timestamp({self.time_precision},{zone})"
            return f"timestamp({zone})"
        if self.kind is Kind.TIME and self.time_precision is not None:
            return f"time({self.time_precision})"
        if self.kind is Kind.ARRAY:
            return f"array<{self.element}>"
        if self.kind is Kind.MAP:
            return f"map<{self.key},{self.value}>"
        if self.kind is Kind.STRUCT:
            inner = ",".join(f"{name}:{type_}" for name, type_ in self.fields)
            return f"struct<{inner}>"
        return self.kind.value

    def describe(self) -> str:
        """A phrase for a person, not a machine."""
        base = {
            Kind.DECIMAL: (
                f"exact decimal with {self.precision} digits, "
                f"{self.scale} after the point"
            ),
            Kind.TIMESTAMP: (
                "timestamp with a timezone"
                if self.tz_aware
                else "timestamp with no timezone"
            ),
            Kind.UNKNOWN: "not determined",
        }.get(self.kind)
        return base if base is not None else str(self)


def replace_nullable(type_: PWType, nullable: bool) -> PWType:
    from dataclasses import replace

    return replace(type_, nullable=nullable)


# -- constructors ---------------------------------------------------------
# Plain names for the common cases, so calling code reads as prose.

BOOLEAN = PWType(Kind.BOOLEAN)
INT8 = PWType(Kind.INT8)
INT16 = PWType(Kind.INT16)
INT32 = PWType(Kind.INT32)
INT64 = PWType(Kind.INT64)
UINT8 = PWType(Kind.UINT8)
UINT16 = PWType(Kind.UINT16)
UINT32 = PWType(Kind.UINT32)
UINT64 = PWType(Kind.UINT64)
FLOAT32 = PWType(Kind.FLOAT32)
FLOAT64 = PWType(Kind.FLOAT64)
STRING = PWType(Kind.STRING)
BYTES = PWType(Kind.BYTES)
DATE = PWType(Kind.DATE)
INTERVAL = PWType(Kind.INTERVAL)
UUID = PWType(Kind.UUID)
JSON = PWType(Kind.JSON)
GEOGRAPHY = PWType(Kind.GEOGRAPHY)
UNKNOWN = PWType(Kind.UNKNOWN)


def decimal(precision: int, scale: int) -> PWType:
    return PWType(Kind.DECIMAL, precision=precision, scale=scale)


def string(max_length: int | None = None) -> PWType:
    return PWType(Kind.STRING, max_length=max_length)


def binary(max_length: int | None = None) -> PWType:
    return PWType(Kind.BYTES, max_length=max_length)


def time(precision: int | None = None) -> PWType:
    return PWType(Kind.TIME, time_precision=precision)


def timestamp(*, tz_aware: bool = False, precision: int | None = None) -> PWType:
    return PWType(Kind.TIMESTAMP, tz_aware=tz_aware, time_precision=precision)


def array(element: PWType) -> PWType:
    return PWType(Kind.ARRAY, element=element)


def struct(fields: dict[str, PWType] | list[tuple[str, PWType]]) -> PWType:
    items = tuple(fields.items()) if isinstance(fields, dict) else tuple(fields)
    return PWType(Kind.STRUCT, fields=items)


def mapping(key: PWType, value: PWType) -> PWType:
    return PWType(Kind.MAP, key=key, value=value)


def parse(text: str) -> PWType:
    """Read back what :meth:`PWType.__str__` wrote.

    Round-tripping matters because types are stored in JSON columns and travel
    over the API as strings; a type that cannot survive that trip is a type the
    platform cannot persist.
    """
    return _parse(text.strip())


def _split_args(text: str) -> list[str]:
    """Split on commas that are not inside angle brackets or parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def _parse(text: str) -> PWType:
    lowered = text.lower()

    if lowered.startswith("array<") and lowered.endswith(">"):
        return array(_parse(text[len("array<") : -1]))
    if lowered.startswith("map<") and lowered.endswith(">"):
        key_text, value_text = _split_args(text[len("map<") : -1])
        return mapping(_parse(key_text), _parse(value_text))
    if lowered.startswith("struct<") and lowered.endswith(">"):
        fields: list[tuple[str, PWType]] = []
        for part in _split_args(text[len("struct<") : -1]):
            name, _, type_text = part.partition(":")
            fields.append((name.strip(), _parse(type_text)))
        return struct(fields)

    name, _, arg_text = lowered.partition("(")
    name = name.strip()
    args = [a.strip() for a in arg_text.rstrip(")").split(",")] if arg_text else []

    if name == "decimal":
        return decimal(int(args[0]), int(args[1]))
    if name == "string":
        return string(int(args[0])) if args and args[0] else STRING
    if name == "bytes":
        return binary(int(args[0])) if args and args[0] else BYTES
    if name == "time":
        return time(int(args[0])) if args and args[0] else PWType(Kind.TIME)
    if name == "timestamp":
        precision: int | None = None
        tz_aware = False
        for arg in args:
            if arg in {"tz", "naive"}:
                tz_aware = arg == "tz"
            elif arg:
                precision = int(arg)
        return timestamp(tz_aware=tz_aware, precision=precision)

    try:
        return PWType(Kind(name))
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Not a Pipewright type: {text!r}") from exc


def to_json(type_: PWType) -> dict[str, Any]:
    """A stable dict for persistence. Uses the string form, which round-trips."""
    return {"type": str(type_), "nullable": type_.nullable}


def from_json(payload: dict[str, Any]) -> PWType:
    parsed = parse(payload["type"])
    return parsed.with_nullable(bool(payload.get("nullable", True)))
