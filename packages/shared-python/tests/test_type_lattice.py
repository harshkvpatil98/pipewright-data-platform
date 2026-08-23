"""The canonical type lattice.

These tests are the specification. The lattice exists because a column's type
used to be one of seven bare strings, which cannot express precision, timezone
awareness, or exactness -- and that gap has already produced silent corruption
in this platform once.
"""

import pytest

from shared_python.types.lattice import (
    BOOLEAN,
    BYTES,
    DATE,
    FLOAT32,
    INT8,
    INT32,
    INT64,
    JSON,
    STRING,
    UINT8,
    UNKNOWN,
    UUID,
    Kind,
    PWType,
    array,
    binary,
    decimal,
    from_json,
    mapping,
    parse,
    string,
    struct,
    time,
    timestamp,
    to_json,
)


class TestConstruction:
    def test_decimal_requires_precision_and_scale(self) -> None:
        # A decimal without them is just a float wearing a hat.
        with pytest.raises(ValueError, match="precision and scale"):
            PWType(Kind.DECIMAL)

    def test_decimal_scale_cannot_exceed_precision(self) -> None:
        with pytest.raises(ValueError, match="scale must be"):
            decimal(4, 6)

    def test_array_requires_an_element_type(self) -> None:
        with pytest.raises(ValueError, match="element type"):
            PWType(Kind.ARRAY)

    def test_struct_requires_fields(self) -> None:
        with pytest.raises(ValueError, match="at least one field"):
            PWType(Kind.STRUCT)

    def test_only_timestamps_carry_timezone_awareness(self) -> None:
        # tz_aware on a DATE would imply an offset that a date does not have.
        with pytest.raises(ValueError, match="Only TIMESTAMP"):
            PWType(Kind.DATE, tz_aware=True)

    def test_fractional_precision_is_bounded(self) -> None:
        with pytest.raises(ValueError, match="0..9"):
            time(12)


class TestIdentity:
    def test_zoned_and_naive_timestamps_are_different_types(self) -> None:
        # The whole point: these must not compare equal, or a pipeline can join
        # them without anyone noticing the offset is missing.
        assert timestamp(tz_aware=True) != timestamp(tz_aware=False)

    def test_decimals_differ_by_scale(self) -> None:
        assert decimal(18, 2) != decimal(18, 4)

    def test_bounded_and_unbounded_strings_differ(self) -> None:
        assert string(10) != string()

    def test_types_are_hashable_so_they_can_key_a_mapping(self) -> None:
        assert len({INT64, INT64, INT32}) == 2

    def test_nullability_is_part_of_the_value(self) -> None:
        assert INT64.with_nullable(False) != INT64


class TestPredicates:
    @pytest.mark.parametrize("type_", [INT8, INT32, INT64, UINT8])
    def test_integers_are_integers(self, type_: PWType) -> None:
        assert type_.is_integer and type_.is_numeric

    def test_decimal_is_numeric_but_not_float(self) -> None:
        value = decimal(10, 2)
        assert value.is_numeric
        assert not value.is_float

    def test_unsigned_is_not_signed(self) -> None:
        assert INT32.is_signed
        assert not UINT8.is_signed

    def test_unknown_reports_itself_as_unknown(self) -> None:
        # It is allowed to survive; guessing is what causes damage.
        assert not UNKNOWN.is_known


class TestRendering:
    @pytest.mark.parametrize(
        ("type_", "expected"),
        [
            (INT64, "int64"),
            (decimal(38, 10), "decimal(38,10)"),
            (string(120), "string(120)"),
            (string(), "string"),
            (timestamp(tz_aware=True), "timestamp(tz)"),
            (timestamp(tz_aware=False), "timestamp(naive)"),
            (timestamp(tz_aware=True, precision=6), "timestamp(6,tz)"),
            (time(3), "time(3)"),
            (array(INT64), "array<int64>"),
            (mapping(STRING, INT64), "map<string,int64>"),
            (struct({"a": INT64, "b": STRING}), "struct<a:int64,b:string>"),
        ],
    )
    def test_string_form(self, type_: PWType, expected: str) -> None:
        assert str(type_) == expected

    @pytest.mark.parametrize(
        "type_",
        [
            INT64,
            FLOAT32,
            BOOLEAN,
            BYTES,
            DATE,
            UUID,
            JSON,
            UNKNOWN,
            decimal(38, 10),
            string(120),
            binary(64),
            time(3),
            timestamp(tz_aware=True, precision=6),
            timestamp(tz_aware=False),
            array(INT64),
            array(array(decimal(10, 2))),
            mapping(STRING, array(INT64)),
            struct({"id": UUID, "tags": array(STRING), "at": timestamp(tz_aware=True)}),
        ],
    )
    def test_every_type_round_trips_through_text(self, type_: PWType) -> None:
        # Types live in JSON columns and travel over the API as strings. One
        # that cannot survive that trip is one the platform cannot persist.
        assert parse(str(type_)) == type_

    def test_round_trips_through_json_including_nullability(self) -> None:
        original = decimal(18, 4).with_nullable(False)
        assert from_json(to_json(original)) == original

    def test_describe_is_written_for_a_person(self) -> None:
        assert "after the point" in decimal(18, 2).describe()
        assert "no timezone" in timestamp(tz_aware=False).describe()
        assert timestamp(tz_aware=True).describe() != timestamp(tz_aware=False).describe()

    def test_parse_rejects_nonsense(self) -> None:
        with pytest.raises(ValueError, match="Not a Pipewright type"):
            parse("bigint")


class TestNestedParsing:
    def test_commas_inside_nested_types_do_not_split_arguments(self) -> None:
        # The naive split on "," turns map<string,decimal(10,2)> into three
        # pieces and produces a wrong type rather than an error.
        parsed = parse("map<string,decimal(10,2)>")
        assert parsed == mapping(STRING, decimal(10, 2))

    def test_deeply_nested_structures_survive(self) -> None:
        original = struct(
            {
                "rows": array(struct({"sku": STRING, "price": decimal(12, 2)})),
                "meta": mapping(STRING, JSON),
            }
        )
        assert parse(str(original)) == original
