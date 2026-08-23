"""What is lost when one type becomes another, and what two types have in common.

The platform's rule is that **a lossy cast is surfaced before the run, not
discovered after it**. That is the same discipline that made chart validation
work in Phase 05 -- "a pie needs one grouping column" beats 900 unreadable
slices -- applied to types. A pipeline that will truncate a decimal or drop a
timezone should say so while it is being built.

Two functions carry that:

``cast_loss(source, target)``
    Everything that would be lost, as a list. Empty means the cast is exact.

``widen(a, b)``
    The narrowest type that can hold both, for unions, joins and coalesce.
    Returns ``None`` when no such type exists, which is itself information.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared_python.types.lattice import (
    FLOAT_SIGNIFICANT_DIGITS,
    INT_RANGE,
    MAX_DECIMAL_PRECISION,
    Kind,
    PWType,
    array,
    decimal,
    mapping,
    string,
    struct,
    timestamp,
)

LossKind = Literal[
    "precision",
    "range",
    "timezone",
    "truncation",
    "nullability",
    "representation",
    "unsupported",
]

#: ``blocking`` -- no correct conversion exists, so the pipeline must not run.
#: ``warning``  -- a conversion exists but is lossy for some or all values.
Severity = Literal["blocking", "warning"]


@dataclass(frozen=True)
class CastLoss:
    kind: LossKind
    detail: str
    severity: Severity = "warning"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind}: {self.detail}"


def _decimal_digits_needed(type_: PWType) -> int | None:
    """How many significant digits an integer kind needs to survive exactly."""
    if type_.kind not in INT_RANGE:
        return None
    low, high = INT_RANGE[type_.kind]
    return len(str(max(abs(low), abs(high))))


def cast_loss(source: PWType, target: PWType) -> list[CastLoss]:
    """Everything lost converting ``source`` to ``target``. Empty means exact."""
    losses: list[CastLoss] = []

    if source.kind is Kind.UNKNOWN or target.kind is Kind.UNKNOWN:
        # Not an error: an untyped column is honest, and refusing to reason
        # about it is better than inventing a type for it.
        return [
            CastLoss(
                "unsupported",
                "One side is not typed, so the conversion cannot be checked.",
                "warning",
            )
        ]

    if not source.nullable and target.nullable:
        pass  # widening nullability is always safe
    if source.nullable and not target.nullable:
        losses.append(
            CastLoss(
                "nullability",
                f"{source} admits nulls but {target} does not; "
                "rows with a null here will be rejected.",
                "warning",
            )
        )

    if source.kind == target.kind and _same_parameters(source, target):
        return losses

    handler = _HANDLERS.get((_family(source), _family(target)))
    if handler is None:
        losses.append(
            CastLoss(
                "unsupported",
                f"There is no defined conversion from {source} to {target}.",
                "blocking",
            )
        )
        return losses

    losses.extend(handler(source, target))
    return losses


def can_cast(source: PWType, target: PWType) -> bool:
    """True when a conversion exists at all, lossy or not."""
    return not any(loss.severity == "blocking" for loss in cast_loss(source, target))


def is_exact(source: PWType, target: PWType) -> bool:
    """True when nothing whatsoever is lost."""
    return not cast_loss(source, target)


def _same_parameters(a: PWType, b: PWType) -> bool:
    return (
        a.precision == b.precision
        and a.scale == b.scale
        and a.max_length == b.max_length
        and a.time_precision == b.time_precision
        and a.tz_aware == b.tz_aware
        and a.element == b.element
        and a.key == b.key
        and a.value == b.value
        and a.fields == b.fields
    )


def _family(type_: PWType) -> str:
    if type_.is_integer:
        return "int"
    if type_.is_float:
        return "float"
    if type_.kind is Kind.DECIMAL:
        return "decimal"
    if type_.kind in (Kind.STRING,):
        return "string"
    if type_.kind is Kind.BYTES:
        return "bytes"
    if type_.kind is Kind.BOOLEAN:
        return "boolean"
    if type_.kind in (Kind.DATE, Kind.TIME, Kind.TIMESTAMP, Kind.INTERVAL):
        return "temporal"
    if type_.is_nested or type_.kind is Kind.JSON:
        return "nested"
    return "scalar"  # uuid, geography


# -- per-family conversions ------------------------------------------------


def _int_to_int(source: PWType, target: PWType) -> list[CastLoss]:
    losses: list[CastLoss] = []
    src_low, src_high = INT_RANGE[source.kind]
    tgt_low, tgt_high = INT_RANGE[target.kind]
    if src_low < tgt_low or src_high > tgt_high:
        losses.append(
            CastLoss(
                "range",
                f"{source} holds {src_low}..{src_high} but {target} holds "
                f"{tgt_low}..{tgt_high}; values outside that range cannot be stored.",
            )
        )
    if source.is_signed and not target.is_signed:
        losses.append(
            CastLoss("range", f"{target} is unsigned; negative values cannot be stored.")
        )
    return losses


def _int_to_float(source: PWType, target: PWType) -> list[CastLoss]:
    needed = _decimal_digits_needed(source) or 0
    available = FLOAT_SIGNIFICANT_DIGITS[target.kind]
    if needed > available:
        return [
            CastLoss(
                "precision",
                f"{source} needs up to {needed} significant digits but {target} "
                f"carries {available}; large values will be rounded.",
            )
        ]
    return []


def _int_to_decimal(source: PWType, target: PWType) -> list[CastLoss]:
    needed = _decimal_digits_needed(source) or 0
    whole_digits = (target.precision or 0) - (target.scale or 0)
    if needed > whole_digits:
        return [
            CastLoss(
                "range",
                f"{source} needs up to {needed} whole digits but {target} leaves "
                f"{whole_digits}; large values will not fit.",
            )
        ]
    return []


def _float_to_int(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "precision",
            f"{source} has a fractional part that {target} cannot hold; "
            "values will be truncated toward zero.",
        )
    ]


def _float_to_float(source: PWType, target: PWType) -> list[CastLoss]:
    if FLOAT_SIGNIFICANT_DIGITS[source.kind] > FLOAT_SIGNIFICANT_DIGITS[target.kind]:
        return [
            CastLoss(
                "precision",
                f"{source} carries {FLOAT_SIGNIFICANT_DIGITS[source.kind]} significant "
                f"digits but {target} carries {FLOAT_SIGNIFICANT_DIGITS[target.kind]}.",
            )
        ]
    return []


def _float_to_decimal(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "representation",
            f"{source} is binary floating point and cannot represent every decimal "
            f"value exactly; converting to {target} rounds to the nearest "
            "representable amount.",
        )
    ]


def _decimal_to_float(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "representation",
            f"{source} is exact but {target} is binary floating point; sums and "
            "comparisons on the result will not be exact. This is the classic "
            "cause of totals that disagree by a penny.",
        )
    ]


def _decimal_to_decimal(source: PWType, target: PWType) -> list[CastLoss]:
    losses: list[CastLoss] = []
    src_scale, tgt_scale = source.scale or 0, target.scale or 0
    src_whole = (source.precision or 0) - src_scale
    tgt_whole = (target.precision or 0) - tgt_scale
    if tgt_scale < src_scale:
        losses.append(
            CastLoss(
                "precision",
                f"{source} keeps {src_scale} decimal places but {target} keeps "
                f"{tgt_scale}; {src_scale - tgt_scale} will be rounded away.",
            )
        )
    if tgt_whole < src_whole:
        losses.append(
            CastLoss(
                "range",
                f"{source} allows {src_whole} whole digits but {target} allows "
                f"{tgt_whole}; larger values will not fit.",
            )
        )
    return losses


def _decimal_to_int(source: PWType, target: PWType) -> list[CastLoss]:
    losses: list[CastLoss] = []
    if (source.scale or 0) > 0:
        losses.append(
            CastLoss(
                "precision",
                f"{source} has {source.scale} decimal places that {target} cannot "
                "hold; values will be truncated.",
            )
        )
    losses.extend(_int_to_decimal_range_check(source, target))
    return losses


def _int_to_decimal_range_check(source: PWType, target: PWType) -> list[CastLoss]:
    whole_digits = (source.precision or 0) - (source.scale or 0)
    _, tgt_high = INT_RANGE[target.kind]
    if whole_digits > len(str(tgt_high)):
        return [
            CastLoss(
                "range",
                f"{source} allows {whole_digits} whole digits, more than {target} holds.",
            )
        ]
    return []


def _to_string(source: PWType, target: PWType) -> list[CastLoss]:
    if target.max_length is None:
        return []
    return [
        CastLoss(
            "truncation",
            f"{target} is bounded; longer rendered values will be cut short.",
        )
    ]


def _string_to_string(source: PWType, target: PWType) -> list[CastLoss]:
    if target.max_length is None:
        return []
    if source.max_length is None or source.max_length > target.max_length:
        return [
            CastLoss(
                "truncation",
                f"{source} allows longer values than {target}; they will be cut short.",
            )
        ]
    return []


def _string_to_other(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "representation",
            f"Text must be parsed to become {target}; values that do not parse "
            "will fail rather than convert.",
        )
    ]


def _temporal_to_temporal(source: PWType, target: PWType) -> list[CastLoss]:
    losses: list[CastLoss] = []
    if source.kind is Kind.TIMESTAMP and target.kind is Kind.TIMESTAMP:
        if source.tz_aware and not target.tz_aware:
            losses.append(
                CastLoss(
                    "timezone",
                    "Dropping the timezone keeps the wall-clock reading and loses "
                    "the offset, so the same instant will read differently after a "
                    "daylight-saving change.",
                    "blocking",
                )
            )
        elif not source.tz_aware and target.tz_aware:
            losses.append(
                CastLoss(
                    "timezone",
                    "A naive timestamp has no offset, so one must be assumed to make "
                    "it zoned. Set the source timezone explicitly rather than "
                    "letting the server's local zone decide.",
                    "blocking",
                )
            )
        src_p = source.time_precision
        tgt_p = target.time_precision
        if src_p is not None and tgt_p is not None and tgt_p < src_p:
            losses.append(
                CastLoss(
                    "precision",
                    f"Fractional seconds drop from {src_p} digits to {tgt_p}.",
                )
            )
        return losses

    if source.kind is Kind.TIMESTAMP and target.kind is Kind.DATE:
        return [CastLoss("precision", "The time of day is discarded.")]
    if source.kind is Kind.TIMESTAMP and target.kind is Kind.TIME:
        return [CastLoss("precision", "The date is discarded.")]
    if source.kind is Kind.DATE and target.kind is Kind.TIMESTAMP:
        return [CastLoss("representation", "Midnight is assumed for the time of day.")]
    if source.kind is Kind.DATE and target.kind is Kind.TIME:
        return [
            CastLoss("unsupported", "A date carries no time of day.", "blocking")
        ]
    if source.kind is Kind.TIME and target.kind in (Kind.DATE, Kind.TIMESTAMP):
        return [CastLoss("unsupported", "A time of day carries no date.", "blocking")]
    if Kind.INTERVAL in (source.kind, target.kind):
        return [
            CastLoss(
                "unsupported",
                f"An interval is a duration, not a point in time; {source} and "
                f"{target} are not interchangeable.",
                "blocking",
            )
        ]
    return []


def _boolean_to_number(source: PWType, target: PWType) -> list[CastLoss]:
    return []  # true/false -> 1/0 is exact everywhere


def _number_to_boolean(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "representation",
            "Every non-zero value becomes true, so distinct numbers collapse "
            "to the same boolean.",
        )
    ]


def _nested_to_nested(source: PWType, target: PWType) -> list[CastLoss]:
    if source.kind is Kind.JSON or target.kind is Kind.JSON:
        return []
    if source.kind is not target.kind:
        return [
            CastLoss(
                "unsupported",
                f"{source} and {target} have different shapes.",
                "blocking",
            )
        ]
    if source.kind is Kind.ARRAY:
        return [
            CastLoss(loss.kind, f"element: {loss.detail}", loss.severity)
            for loss in cast_loss(source.element, target.element)  # type: ignore[arg-type]
        ]
    if source.kind is Kind.MAP:
        losses = [
            CastLoss(loss.kind, f"key: {loss.detail}", loss.severity)
            for loss in cast_loss(source.key, target.key)  # type: ignore[arg-type]
        ]
        losses += [
            CastLoss(loss.kind, f"value: {loss.detail}", loss.severity)
            for loss in cast_loss(source.value, target.value)  # type: ignore[arg-type]
        ]
        return losses
    # STRUCT
    losses = []
    source_fields = dict(source.fields)
    target_fields = dict(target.fields)
    for name in source_fields.keys() - target_fields.keys():
        losses.append(
            CastLoss("unsupported", f"field {name!r} has nowhere to go.", "blocking")
        )
    for name, target_type in target_fields.items():
        if name not in source_fields:
            losses.append(
                CastLoss("nullability", f"field {name!r} has no source and will be null.")
            )
            continue
        losses += [
            CastLoss(loss.kind, f"field {name!r}: {loss.detail}", loss.severity)
            for loss in cast_loss(source_fields[name], target_type)
        ]
    return losses


def _nested_to_string(source: PWType, target: PWType) -> list[CastLoss]:
    losses = [
        CastLoss(
            "representation",
            f"{source} is serialised to text; the structure is no longer queryable.",
        )
    ]
    losses.extend(_to_string(source, target))
    return losses


def _unsupported(source: PWType, target: PWType) -> list[CastLoss]:
    return [
        CastLoss(
            "unsupported",
            f"There is no defined conversion from {source} to {target}.",
            "blocking",
        )
    ]


_HANDLERS = {
    ("int", "int"): _int_to_int,
    ("int", "float"): _int_to_float,
    ("int", "decimal"): _int_to_decimal,
    ("int", "string"): _to_string,
    ("int", "boolean"): _number_to_boolean,
    ("float", "int"): _float_to_int,
    ("float", "float"): _float_to_float,
    ("float", "decimal"): _float_to_decimal,
    ("float", "string"): _to_string,
    ("float", "boolean"): _number_to_boolean,
    ("decimal", "int"): _decimal_to_int,
    ("decimal", "float"): _decimal_to_float,
    ("decimal", "decimal"): _decimal_to_decimal,
    ("decimal", "string"): _to_string,
    ("boolean", "int"): _boolean_to_number,
    ("boolean", "float"): _boolean_to_number,
    ("boolean", "decimal"): _boolean_to_number,
    ("boolean", "string"): _to_string,
    ("string", "string"): _string_to_string,
    ("string", "int"): _string_to_other,
    ("string", "float"): _string_to_other,
    ("string", "decimal"): _string_to_other,
    ("string", "boolean"): _string_to_other,
    ("string", "temporal"): _string_to_other,
    ("string", "scalar"): _string_to_other,
    ("string", "nested"): _string_to_other,
    ("string", "bytes"): lambda s, t: [
        CastLoss("representation", "Text is encoded as UTF-8 bytes.")
    ],
    ("bytes", "bytes"): _string_to_string,
    ("bytes", "string"): lambda s, t: [
        CastLoss(
            "representation",
            "Bytes are decoded as UTF-8; sequences that are not valid UTF-8 will fail.",
        )
    ],
    ("temporal", "temporal"): _temporal_to_temporal,
    ("temporal", "string"): _to_string,
    ("scalar", "string"): _to_string,
    ("nested", "nested"): _nested_to_nested,
    ("nested", "string"): _nested_to_string,
}


# -- widening --------------------------------------------------------------


def widen(a: PWType, b: PWType) -> PWType | None:
    """The narrowest type holding both, or ``None`` when none exists.

    Used wherever two columns must become one: unions, join keys, coalesce.
    Returning ``None`` rather than falling back to STRING is deliberate --
    silently stringifying a union of a timestamp and an integer produces a
    column nobody can compute with, and hides the mistake.
    """
    if a == b:
        return a

    nullable = a.nullable or b.nullable

    if a.kind is Kind.UNKNOWN:
        return b.with_nullable(nullable)
    if b.kind is Kind.UNKNOWN:
        return a.with_nullable(nullable)

    if a.is_integer and b.is_integer:
        return _widen_int(a, b).with_nullable(nullable)

    if a.is_numeric and b.is_numeric:
        if a.kind is Kind.DECIMAL or b.kind is Kind.DECIMAL:
            widened = _widen_decimal(a, b)
            return widened.with_nullable(nullable) if widened else None
        # int + float, or float + float: the wider float wins.
        if FLOAT_SIGNIFICANT_DIGITS.get(a.kind, 0) >= FLOAT_SIGNIFICANT_DIGITS.get(
            b.kind, 0
        ):
            float_side = a if a.is_float else b
        else:
            float_side = b if b.is_float else a
        return float_side.with_nullable(nullable)

    if a.kind is Kind.STRING and b.kind is Kind.STRING:
        if a.max_length is None or b.max_length is None:
            return string().with_nullable(nullable)
        return string(max(a.max_length, b.max_length)).with_nullable(nullable)

    if a.kind is Kind.TIMESTAMP and b.kind is Kind.TIMESTAMP:
        if a.tz_aware != b.tz_aware:
            # No safe answer: one side has no offset. Say so instead of guessing.
            return None
        precision = max(a.time_precision or 0, b.time_precision or 0) or None
        return timestamp(tz_aware=a.tz_aware, precision=precision).with_nullable(nullable)

    if {a.kind, b.kind} == {Kind.DATE, Kind.TIMESTAMP}:
        stamp = a if a.kind is Kind.TIMESTAMP else b
        return stamp.with_nullable(nullable)

    if a.kind is Kind.ARRAY and b.kind is Kind.ARRAY:
        element = widen(a.element, b.element)  # type: ignore[arg-type]
        return array(element).with_nullable(nullable) if element else None

    if a.kind is Kind.MAP and b.kind is Kind.MAP:
        key = widen(a.key, b.key)  # type: ignore[arg-type]
        value = widen(a.value, b.value)  # type: ignore[arg-type]
        return mapping(key, value).with_nullable(nullable) if key and value else None

    if a.kind is Kind.STRUCT and b.kind is Kind.STRUCT:
        merged: list[tuple[str, PWType]] = []
        names = list(dict.fromkeys([n for n, _ in a.fields] + [n for n, _ in b.fields]))
        a_fields, b_fields = dict(a.fields), dict(b.fields)
        for name in names:
            if name in a_fields and name in b_fields:
                field_type = widen(a_fields[name], b_fields[name])
                if field_type is None:
                    return None
            else:
                # Present on one side only, so it is null on the other.
                field_type = (a_fields.get(name) or b_fields[name]).with_nullable(True)
            merged.append((name, field_type))
        return struct(merged).with_nullable(nullable)

    return None


def _widen_int(a: PWType, b: PWType) -> PWType:
    a_low, a_high = INT_RANGE[a.kind]
    b_low, b_high = INT_RANGE[b.kind]
    need_low, need_high = min(a_low, b_low), max(a_high, b_high)
    for kind in (
        Kind.INT8,
        Kind.UINT8,
        Kind.INT16,
        Kind.UINT16,
        Kind.INT32,
        Kind.UINT32,
        Kind.INT64,
        Kind.UINT64,
    ):
        low, high = INT_RANGE[kind]
        if low <= need_low and high >= need_high:
            return PWType(kind)
    # A signed and an unsigned 64-bit column together exceed either one. Falling
    # back to DECIMAL keeps every value exact rather than overflowing silently.
    return decimal(20, 0)


def _widen_decimal(a: PWType, b: PWType) -> PWType | None:
    def parts(type_: PWType) -> tuple[int, int]:
        if type_.kind is Kind.DECIMAL:
            return (type_.precision or 0) - (type_.scale or 0), type_.scale or 0
        if type_.is_integer:
            _, high = INT_RANGE[type_.kind]
            return len(str(high)), 0
        # A float cannot be widened into a decimal without deciding how many
        # digits to keep, and any choice would be arbitrary.
        return -1, -1

    a_whole, a_scale = parts(a)
    b_whole, b_scale = parts(b)
    if a_whole < 0 or b_whole < 0:
        return None
    whole, scale = max(a_whole, b_whole), max(a_scale, b_scale)
    if whole + scale > MAX_DECIMAL_PRECISION:
        return None
    return decimal(whole + scale, scale)
