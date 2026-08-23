"""Bidirectional type mappings between each source and the canonical lattice.

Every source maps *into* :class:`PWType` and the lattice maps *out* to every
destination, so there are 2N conversions to maintain rather than N-squared.

Each mapping is a pair -- ``to_pw`` reads a source type name, ``from_pw`` emits
one -- plus a declaration of what the source cannot represent, so a pipeline
targeting it can be checked before it runs rather than after it fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared_python.types.lattice import (
    BOOLEAN,
    BYTES,
    DATE,
    FLOAT32,
    FLOAT64,
    GEOGRAPHY,
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
    array,
    binary,
    decimal,
    string,
    time,
    timestamp,
)

#: ``varchar(80)`` -> ("varchar", [80]);  ``numeric(38, 10)`` -> ("numeric", [38, 10])
_PARAMS = re.compile(r"^\s*([a-z0-9_ ]+?)\s*(?:\(\s*([^)]*)\s*\))?\s*$", re.I)


def _split(source_type: str) -> tuple[str, list[int]]:
    match = _PARAMS.match(source_type.strip())
    if match is None:
        return source_type.strip().lower(), []
    name = " ".join(match.group(1).lower().split())
    args: list[int] = []
    if match.group(2):
        for part in match.group(2).split(","):
            part = part.strip()
            if part.isdigit():
                args.append(int(part))
    return name, args


@dataclass(frozen=True)
class TypeMapping:
    """How one source's type names correspond to the lattice."""

    name: str
    #: Exact source-type name -> canonical type, for the unparameterised cases.
    simple: dict[str, PWType] = field(default_factory=dict)
    #: Kinds this source cannot store at all.
    unsupported: frozenset[Kind] = frozenset()
    #: Human-readable note about the source's quirks, surfaced in the UI.
    caveat: str = ""

    def to_pw(self, source_type: str) -> PWType:
        """Read a source type name. Unrecognised names become UNKNOWN, never a guess."""
        name, args = _split(source_type)
        handler = getattr(self, "_to_pw_special", None)
        if handler is not None:
            special = handler(name, args)
            if special is not None:
                return special
        return self.simple.get(name, UNKNOWN)

    def from_pw(self, type_: PWType) -> str:
        raise NotImplementedError

    def supports(self, type_: PWType) -> bool:
        return type_.kind not in self.unsupported


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


class PostgresMapping(TypeMapping):
    def __init__(self) -> None:
        super().__init__(
            name="postgres",
            simple={
                "bool": BOOLEAN, "boolean": BOOLEAN,
                "int2": INT16, "smallint": INT16,
                "int4": INT32, "int": INT32, "integer": INT32,
                "int8": INT64, "bigint": INT64,
                "float4": FLOAT32, "real": FLOAT32,
                "float8": FLOAT64, "double precision": FLOAT64,
                "text": STRING, "citext": STRING, "name": STRING,
                "bytea": BYTES,
                "date": DATE,
                "uuid": UUID,
                "json": JSON, "jsonb": JSON,
                "interval": INTERVAL,
                "geography": GEOGRAPHY, "geometry": GEOGRAPHY,
                "serial": INT32, "bigserial": INT64,
                "money": decimal(19, 2),
                "inet": STRING, "cidr": STRING, "macaddr": STRING, "xml": STRING,
            },
            caveat=(
                "timestamptz stores an instant and renders in the session timezone; "
                "timestamp stores a wall-clock reading with no offset at all."
            ),
        )

    def _to_pw_special(self, name: str, args: list[int]) -> PWType | None:
        if name in ("numeric", "decimal"):
            # Unqualified NUMERIC is arbitrary precision. Nothing else here can
            # hold that, so it is reported rather than silently bounded.
            if not args:
                return decimal(38, 9)
            return decimal(args[0], args[1] if len(args) > 1 else 0)
        if name in ("varchar", "character varying"):
            return string(args[0]) if args else STRING
        if name in ("char", "character", "bpchar"):
            return string(args[0] if args else 1)
        if name == "timestamptz" or name == "timestamp with time zone":
            return timestamp(tz_aware=True, precision=args[0] if args else 6)
        if name == "timestamp" or name == "timestamp without time zone":
            return timestamp(tz_aware=False, precision=args[0] if args else 6)
        if name in ("timetz", "time with time zone", "time", "time without time zone"):
            return time(args[0] if args else 6)
        if name.endswith("[]"):
            return array(self.to_pw(name[:-2]))
        return None

    def from_pw(self, type_: PWType) -> str:
        k = type_.kind
        if k is Kind.BOOLEAN:
            return "boolean"
        if k in (Kind.INT8, Kind.INT16, Kind.UINT8):
            return "smallint"
        if k in (Kind.INT32, Kind.UINT16):
            return "integer"
        if k in (Kind.INT64, Kind.UINT32):
            return "bigint"
        if k is Kind.UINT64:
            # No unsigned 64-bit integer in Postgres; an exact decimal is the
            # only type that holds the whole range.
            return "numeric(20,0)"
        if k is Kind.FLOAT32:
            return "real"
        if k is Kind.FLOAT64:
            return "double precision"
        if k is Kind.DECIMAL:
            return f"numeric({type_.precision},{type_.scale})"
        if k is Kind.STRING:
            return f"varchar({type_.max_length})" if type_.max_length else "text"
        if k is Kind.BYTES:
            return "bytea"
        if k is Kind.DATE:
            return "date"
        if k is Kind.TIME:
            return "time"
        if k is Kind.TIMESTAMP:
            return "timestamptz" if type_.tz_aware else "timestamp"
        if k is Kind.INTERVAL:
            return "interval"
        if k is Kind.UUID:
            return "uuid"
        if k is Kind.JSON:
            return "jsonb"
        if k is Kind.ARRAY:
            return f"{self.from_pw(type_.element)}[]"  # type: ignore[arg-type]
        if k in (Kind.STRUCT, Kind.MAP):
            return "jsonb"
        if k is Kind.GEOGRAPHY:
            return "geography"
        return "text"


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


class MySQLMapping(TypeMapping):
    def __init__(self) -> None:
        super().__init__(
            name="mysql",
            simple={
                "boolean": BOOLEAN, "bool": BOOLEAN,
                "mediumint": INT32,
                "float": FLOAT32,
                "double": FLOAT64, "double precision": FLOAT64, "real": FLOAT64,
                "text": STRING, "tinytext": STRING,
                "mediumtext": STRING, "longtext": STRING,
                "blob": BYTES, "tinyblob": BYTES,
                "mediumblob": BYTES, "longblob": BYTES,
                "date": DATE,
                "json": JSON,
                "geometry": GEOGRAPHY,
                "year": INT16,
            },
            unsupported=frozenset({Kind.ARRAY, Kind.STRUCT, Kind.MAP, Kind.UUID, Kind.INTERVAL}),
            caveat=(
                "DATETIME has no timezone; TIMESTAMP is converted to UTC on write and "
                "back to the session timezone on read, so the two are not "
                "interchangeable. MySQL has no native UUID or array type."
            ),
        )

    def _to_pw_special(self, name: str, args: list[int]) -> PWType | None:
        unsigned = name.endswith(" unsigned")
        if unsigned:
            name = name[: -len(" unsigned")].strip()

        ints = {
            "tinyint": (INT8, UINT8),
            "smallint": (INT16, UINT16),
            "int": (INT32, UINT32), "integer": (INT32, UINT32),
            "bigint": (INT64, UINT64),
        }
        if name in ints:
            # tinyint(1) is MySQL's boolean; the driver returns 0/1 and every
            # ORM in existence treats it as a flag.
            if name == "tinyint" and args and args[0] == 1 and not unsigned:
                return BOOLEAN
            signed_type, unsigned_type = ints[name]
            return unsigned_type if unsigned else signed_type
        if name in ("decimal", "numeric", "dec"):
            return decimal(args[0] if args else 10, args[1] if len(args) > 1 else 0)
        if name in ("varchar", "char"):
            return string(args[0]) if args else STRING
        if name in ("varbinary", "binary"):
            return binary(args[0]) if args else BYTES
        if name == "datetime":
            return timestamp(tz_aware=False, precision=args[0] if args else 0)
        if name == "timestamp":
            return timestamp(tz_aware=True, precision=args[0] if args else 0)
        if name == "time":
            return time(args[0] if args else 0)
        if name in ("enum", "set"):
            return STRING
        return None

    def from_pw(self, type_: PWType) -> str:
        k = type_.kind
        mapping = {
            Kind.BOOLEAN: "tinyint(1)",
            Kind.INT8: "tinyint", Kind.INT16: "smallint",
            Kind.INT32: "int", Kind.INT64: "bigint",
            Kind.UINT8: "tinyint unsigned", Kind.UINT16: "smallint unsigned",
            Kind.UINT32: "int unsigned", Kind.UINT64: "bigint unsigned",
            Kind.FLOAT32: "float", Kind.FLOAT64: "double",
            Kind.BYTES: "longblob", Kind.DATE: "date", Kind.TIME: "time",
            Kind.JSON: "json", Kind.GEOGRAPHY: "geometry",
            # No native type: stored as text, which is why `unsupported` lists it.
            Kind.UUID: "char(36)", Kind.INTERVAL: "varchar(64)",
            Kind.ARRAY: "json", Kind.STRUCT: "json", Kind.MAP: "json",
        }
        if k is Kind.DECIMAL:
            return f"decimal({type_.precision},{type_.scale})"
        if k is Kind.STRING:
            return f"varchar({type_.max_length})" if type_.max_length else "longtext"
        if k is Kind.TIMESTAMP:
            return "timestamp" if type_.tz_aware else "datetime"
        return mapping.get(k, "longtext")


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


class SQLiteMapping(TypeMapping):
    def __init__(self) -> None:
        super().__init__(
            name="sqlite",
            simple={
                "integer": INT64, "int": INT64, "bigint": INT64,
                "smallint": INT16, "tinyint": INT8,
                "real": FLOAT64, "double": FLOAT64, "float": FLOAT64,
                "text": STRING, "clob": STRING,
                "blob": BYTES,
                "boolean": BOOLEAN, "bool": BOOLEAN,
                "date": DATE,
                "json": JSON,
            },
            unsupported=frozenset(
                {Kind.ARRAY, Kind.STRUCT, Kind.MAP, Kind.INTERVAL, Kind.GEOGRAPHY}
            ),
            caveat=(
                "SQLite has type AFFINITY, not types: a column declared NUMERIC will "
                "convert a value that looks numeric. An all-digit UUID stored in such "
                "a column becomes a float and is silently corrupted -- which is exactly "
                "the bug that made this platform switch every model to sqlalchemy.Uuid."
            ),
        )

    def _to_pw_special(self, name: str, args: list[int]) -> PWType | None:
        if name in ("varchar", "character", "nvarchar", "nchar", "char"):
            return string(args[0]) if args else STRING
        if name in ("decimal", "numeric"):
            # Declared NUMERIC gives affinity, not exactness. Reporting it as
            # DECIMAL would promise precision SQLite does not keep.
            return decimal(args[0], args[1]) if len(args) > 1 else UNKNOWN
        if name in ("datetime", "timestamp"):
            return timestamp(tz_aware=False)
        return None

    def from_pw(self, type_: PWType) -> str:
        if type_.is_integer or type_.kind is Kind.BOOLEAN:
            return "INTEGER"
        if type_.is_float:
            return "REAL"
        if type_.kind is Kind.DECIMAL:
            # TEXT, deliberately: NUMERIC affinity would convert it to a float
            # and lose the exactness the DECIMAL type exists to guarantee.
            return "TEXT"
        if type_.kind is Kind.BYTES:
            return "BLOB"
        return "TEXT"


# ---------------------------------------------------------------------------
# pandas / Arrow
# ---------------------------------------------------------------------------


class PandasMapping(TypeMapping):
    def __init__(self) -> None:
        super().__init__(
            name="pandas",
            simple={
                "bool": BOOLEAN, "boolean": BOOLEAN,
                "int8": INT8, "int16": INT16, "int32": INT32, "int64": INT64,
                "uint8": UINT8, "uint16": UINT16, "uint32": UINT32, "uint64": UINT64,
                "int8[pyarrow]": INT8, "int64[pyarrow]": INT64,
                "float32": FLOAT32, "float64": FLOAT64,
                "object": UNKNOWN,      # honest: object holds anything
                "string": STRING, "string[python]": STRING, "large_string": STRING,
                "category": STRING,
                "datetime64[ns]": timestamp(tz_aware=False, precision=9),
                "datetime64[us]": timestamp(tz_aware=False, precision=6),
                "datetime64[ms]": timestamp(tz_aware=False, precision=3),
                "timedelta64[ns]": INTERVAL,
                "date32[day]": DATE, "date64[ms]": DATE,
                "binary": BYTES, "large_binary": BYTES,
                "null": UNKNOWN,
            },
            caveat=(
                "A pandas 'object' column can hold anything, so it maps to UNKNOWN "
                "rather than being guessed into a string. Exact decimals are held as "
                "Python Decimal inside an object column."
            ),
        )

    def _to_pw_special(self, name: str, args: list[int]) -> PWType | None:
        # datetime64[ns, Europe/London] -- timezone-aware, whatever the zone.
        if name.startswith("datetime64[") and "," in name:
            unit = name.split("[", 1)[1].split(",", 1)[0].strip()
            return timestamp(tz_aware=True, precision={"s": 0, "ms": 3, "us": 6, "ns": 9}.get(unit, 9))
        if name.startswith("decimal128") or name.startswith("decimal256"):
            return decimal(args[0], args[1]) if len(args) > 1 else UNKNOWN
        if name.startswith("timestamp["):
            inner = name[len("timestamp[") :].rstrip("]")
            unit = inner.split(",")[0].strip()
            tz_aware = "," in inner
            return timestamp(tz_aware=tz_aware, precision={"s": 0, "ms": 3, "us": 6, "ns": 9}.get(unit, 6))
        return None

    def from_pw(self, type_: PWType) -> str:
        k = type_.kind
        if k is Kind.BOOLEAN:
            return "boolean"
        if type_.is_integer:
            # Nullable extension dtypes: numpy int64 cannot hold NA and silently
            # promotes the whole column to float the moment one appears.
            return k.value.capitalize() if type_.nullable else k.value
        if type_.is_float:
            return k.value
        if k is Kind.DECIMAL:
            return "object"  # holds Decimal exactly; float64 would not
        if k is Kind.STRING:
            return "string"
        if k is Kind.TIMESTAMP:
            unit = {0: "s", 3: "ms", 6: "us", 9: "ns"}.get(type_.time_precision or 9, "ns")
            return f"datetime64[{unit}, UTC]" if type_.tz_aware else f"datetime64[{unit}]"
        if k is Kind.DATE:
            return "object"
        if k is Kind.INTERVAL:
            return "timedelta64[ns]"
        return "object"


_REGISTRY: dict[str, TypeMapping] = {}


def register(mapping: TypeMapping) -> TypeMapping:
    _REGISTRY[mapping.name] = mapping
    return mapping


for _mapping in (PostgresMapping(), MySQLMapping(), SQLiteMapping(), PandasMapping()):
    register(_mapping)

# Dialects that share a type system with one already defined.
_REGISTRY["postgresql"] = _REGISTRY["postgres"]
_REGISTRY["redshift"] = _REGISTRY["postgres"]
_REGISTRY["mariadb"] = _REGISTRY["mysql"]
_REGISTRY["arrow"] = _REGISTRY["pandas"]
_REGISTRY["parquet"] = _REGISTRY["pandas"]


def get(name: str) -> TypeMapping:
    key = name.strip().lower()
    if key not in _REGISTRY:
        raise KeyError(
            f"No type mapping for {name!r}. Known: {', '.join(sorted(_REGISTRY))}."
        )
    return _REGISTRY[key]


def known() -> list[str]:
    return sorted(_REGISTRY)
