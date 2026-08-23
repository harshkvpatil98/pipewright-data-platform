"""Coercion and lossy-cast reporting.

The platform's rule is that a lossy cast is surfaced *before* a run, not
discovered after it. These tests pin the losses that matter and, just as
importantly, pin the conversions that are exact -- a system that cries wolf on
safe casts gets ignored on the dangerous ones.
"""

import pytest

from shared_python.types.coercion import CastLoss, can_cast, cast_loss, is_exact, widen
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
    STRING,
    UINT8,
    UINT64,
    UNKNOWN,
    UUID,
    PWType,
    array,
    decimal,
    mapping,
    string,
    struct,
    time,
    timestamp,
)


def kinds(losses: list[CastLoss]) -> set[str]:
    return {loss.kind for loss in losses}


class TestExactConversions:
    """Nothing should be reported when nothing is lost."""

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (INT8, INT16),
            (INT16, INT32),
            (INT32, INT64),
            (UINT8, INT16),
            (FLOAT32, FLOAT64),
            (INT32, FLOAT64),
            (BOOLEAN, INT32),
            (decimal(10, 2), decimal(12, 4)),
            (string(10), string(20)),
            (string(10), string()),
            (timestamp(tz_aware=True), timestamp(tz_aware=True)),
        ],
    )
    def test_widening_is_silent(self, source: PWType, target: PWType) -> None:
        assert cast_loss(source, target) == [], f"{source} -> {target} should be exact"
        assert is_exact(source, target)

    def test_identity_is_exact(self) -> None:
        assert is_exact(decimal(38, 10), decimal(38, 10))


class TestNumericLoss:
    def test_narrowing_an_integer_reports_range(self) -> None:
        losses = cast_loss(INT64, INT32)
        assert kinds(losses) == {"range"}
        assert "2147483647" in losses[0].detail

    def test_signed_to_unsigned_reports_negatives(self) -> None:
        losses = cast_loss(INT32, UINT64)
        assert any("negative" in loss.detail for loss in losses)

    def test_int64_into_float64_loses_precision(self) -> None:
        # float64 carries 15 significant digits; int64 needs 19.
        losses = cast_loss(INT64, FLOAT64)
        assert kinds(losses) == {"precision"}

    def test_int32_into_float64_is_exact(self) -> None:
        assert is_exact(INT32, FLOAT64)

    def test_decimal_to_float_is_flagged_as_representation(self) -> None:
        # The single most consequential cast in financial ETL.
        losses = cast_loss(decimal(18, 2), FLOAT64)
        assert kinds(losses) == {"representation"}
        assert "exact" in losses[0].detail

    def test_reducing_decimal_scale_reports_the_digits_lost(self) -> None:
        losses = cast_loss(decimal(38, 10), decimal(38, 9))
        assert kinds(losses) == {"precision"}
        assert "1 will be rounded away" in losses[0].detail

    def test_reducing_decimal_whole_digits_reports_range(self) -> None:
        losses = cast_loss(decimal(38, 2), decimal(10, 2))
        assert "range" in kinds(losses)

    def test_float_to_int_truncates(self) -> None:
        assert kinds(cast_loss(FLOAT64, INT64)) == {"precision"}

    def test_number_to_boolean_collapses_values(self) -> None:
        losses = cast_loss(INT64, BOOLEAN)
        assert "collapse" in losses[0].detail


class TestTemporalLoss:
    def test_dropping_a_timezone_is_blocking(self) -> None:
        # Not a warning: the same instant reads differently after a DST change,
        # and the error is invisible until six months later.
        losses = cast_loss(timestamp(tz_aware=True), timestamp(tz_aware=False))
        assert losses[0].severity == "blocking"
        assert losses[0].kind == "timezone"

    def test_adding_a_timezone_is_blocking(self) -> None:
        # There is no offset to add, so one would have to be invented.
        losses = cast_loss(timestamp(tz_aware=False), timestamp(tz_aware=True))
        assert losses[0].severity == "blocking"

    def test_reducing_fractional_seconds_reports_precision(self) -> None:
        losses = cast_loss(
            timestamp(tz_aware=True, precision=9), timestamp(tz_aware=True, precision=3)
        )
        assert kinds(losses) == {"precision"}

    def test_timestamp_to_date_discards_the_time(self) -> None:
        assert "time of day is discarded" in cast_loss(timestamp(), DATE)[0].detail

    def test_date_to_time_has_no_meaning(self) -> None:
        losses = cast_loss(DATE, time())
        assert losses[0].severity == "blocking"

    def test_date_to_timestamp_states_the_assumption(self) -> None:
        assert "Midnight is assumed" in cast_loss(DATE, timestamp())[0].detail


class TestTextAndStructure:
    def test_bounded_string_truncation_is_reported(self) -> None:
        assert kinds(cast_loss(string(200), string(50))) == {"truncation"}

    def test_unbounded_into_bounded_is_reported(self) -> None:
        assert kinds(cast_loss(string(), string(50))) == {"truncation"}

    def test_parsing_text_can_fail(self) -> None:
        losses = cast_loss(STRING, INT64)
        assert "do not parse" in losses[0].detail

    def test_struct_field_with_nowhere_to_go_is_blocking(self) -> None:
        losses = cast_loss(
            struct({"a": INT64, "b": STRING}), struct({"a": INT64})
        )
        assert any(loss.severity == "blocking" and "'b'" in loss.detail for loss in losses)

    def test_struct_reports_losses_per_field_with_the_field_named(self) -> None:
        losses = cast_loss(
            struct({"amount": decimal(18, 4)}), struct({"amount": decimal(18, 2)})
        )
        assert "field 'amount'" in losses[0].detail

    def test_array_reports_element_losses(self) -> None:
        losses = cast_loss(array(INT64), array(INT32))
        assert losses[0].detail.startswith("element:")

    def test_map_reports_key_and_value_separately(self) -> None:
        losses = cast_loss(
            mapping(STRING, decimal(18, 4)), mapping(string(4), decimal(18, 2))
        )
        assert any(loss.detail.startswith("key:") for loss in losses)
        assert any(loss.detail.startswith("value:") for loss in losses)

    def test_serialising_structure_to_text_says_it_is_no_longer_queryable(self) -> None:
        assert "no longer queryable" in cast_loss(struct({"a": INT64}), STRING)[0].detail


class TestImpossibleConversions:
    @pytest.mark.parametrize(
        ("source", "target"),
        [(timestamp(), INT64), (UUID, INT64), (array(INT64), INT64), (BYTES, INT64)],
    )
    def test_meaningless_conversions_are_blocking(
        self, source: PWType, target: PWType
    ) -> None:
        assert not can_cast(source, target)

    def test_anything_can_become_text(self) -> None:
        for source in (INT64, decimal(10, 2), timestamp(), UUID, array(INT64), BOOLEAN):
            assert can_cast(source, STRING), f"{source} should render as text"


class TestNullability:
    def test_losing_nullability_is_reported(self) -> None:
        losses = cast_loss(INT64, INT64.with_nullable(False))
        assert kinds(losses) == {"nullability"}

    def test_gaining_nullability_is_silent(self) -> None:
        assert is_exact(INT64.with_nullable(False), INT64)


class TestUnknown:
    def test_unknown_is_never_silently_converted(self) -> None:
        assert cast_loss(UNKNOWN, INT64)[0].kind == "unsupported"
        assert cast_loss(INT64, UNKNOWN)[0].kind == "unsupported"

    def test_unknown_does_not_block_a_pipeline(self) -> None:
        # It is a warning, not a refusal: an untyped column is common on first
        # upload and the user is entitled to proceed.
        assert can_cast(UNKNOWN, INT64)


class TestWidening:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            (INT32, INT64, INT64),
            (INT8, INT16, INT16),
            (UINT8, INT8, INT16),          # neither holds the other's range
            (INT32, FLOAT64, FLOAT64),
            (FLOAT32, FLOAT64, FLOAT64),
            (decimal(10, 2), decimal(8, 4), decimal(12, 4)),
            (decimal(10, 2), INT32, decimal(12, 2)),
            (string(10), string(30), string(30)),
            (string(10), STRING, STRING),
            (DATE, timestamp(), timestamp()),
        ],
    )
    def test_common_supertype(self, a: PWType, b: PWType, expected: PWType) -> None:
        assert widen(a, b) == expected
        assert widen(b, a) == expected, "widening must be symmetric"

    def test_unknown_defers_to_the_known_side(self) -> None:
        assert widen(UNKNOWN, INT64) == INT64
        assert widen(INT64, UNKNOWN) == INT64

    def test_mixed_timezone_awareness_has_no_common_type(self) -> None:
        # Returning None rather than picking one is the point: there is no
        # correct answer, and inventing an offset is how reports drift.
        assert widen(timestamp(tz_aware=True), timestamp(tz_aware=False)) is None

    def test_unrelated_types_have_no_common_type(self) -> None:
        # Falling back to STRING here would produce a column nobody can compute
        # with, and would hide the mistake that led to it.
        assert widen(INT64, timestamp()) is None
        assert widen(INT64, STRING) is None

    def test_signed_and_unsigned_64_bit_widen_to_exact_decimal(self) -> None:
        # Neither int64 nor uint64 holds the other's full range.
        assert widen(INT64, UINT64) == decimal(20, 0)

    def test_nested_types_widen_element_wise(self) -> None:
        assert widen(array(INT32), array(INT64)) == array(INT64)
        assert widen(mapping(STRING, INT32), mapping(STRING, INT64)) == mapping(
            STRING, INT64
        )

    def test_structs_merge_and_absent_fields_become_nullable(self) -> None:
        merged = widen(struct({"a": INT32}), struct({"a": INT64, "b": STRING}))
        assert merged is not None
        fields = dict(merged.fields)
        assert fields["a"] == INT64
        assert fields["b"].nullable

    def test_widening_propagates_nullability(self) -> None:
        assert widen(INT32.with_nullable(False), INT64).nullable

    def test_nested_widening_fails_when_elements_cannot_meet(self) -> None:
        assert widen(array(INT64), array(timestamp())) is None
