"""Inferring a canonical type from real values.

Includes a differential test against the legacy ``infer_series_type``: the two
must agree for every column shape the platform has seen, because two dozen call
sites and every stored dataset schema still speak the old vocabulary.
"""

import datetime as dt
import uuid as uuid_module
from decimal import Decimal

import pandas as pd
import pytest

from shared_python.types.inference import infer_pw_type, to_legacy_name
from shared_python.types.lattice import (
    BOOLEAN,
    FLOAT64,
    INT16,
    INT64,
    STRING,
    UNKNOWN,
    Kind,
    decimal,
)


class TestDeclaredDtypes:
    @pytest.mark.parametrize(
        ("series", "expected"),
        [
            (pd.Series([1, 2, 3]), INT64),
            (pd.Series([1, 2, 3], dtype="int16"), INT16),
            (pd.Series([1.5, 2.5]), FLOAT64),
            (pd.Series([True, False]), BOOLEAN),
            (pd.Series(["a", "b"], dtype="string"), STRING),
        ],
    )
    def test_uses_the_declared_dtype(self, series: pd.Series, expected) -> None:
        assert infer_pw_type(series).kind == expected.kind

    def test_timezone_awareness_comes_from_the_dtype(self) -> None:
        assert infer_pw_type(pd.Series(pd.to_datetime(["2026-01-01"], utc=True))).tz_aware
        assert not infer_pw_type(pd.Series(pd.to_datetime(["2026-01-01"]))).tz_aware

    def test_nullability_is_detected(self) -> None:
        assert infer_pw_type(pd.Series([1, 2, None])).nullable
        assert not infer_pw_type(pd.Series([1, 2, 3])).nullable


class TestObjectColumns:
    """Object dtype declares nothing, so the values are the only evidence."""

    def test_decimals_get_a_precision_that_holds_every_value(self) -> None:
        series = pd.Series([Decimal("1.25"), Decimal("1234.5678")])
        assert infer_pw_type(series) == decimal(8, 4).with_nullable(False)

    def test_decimals_are_never_reported_as_float(self) -> None:
        # The whole reason DECIMAL exists.
        assert infer_pw_type(pd.Series([Decimal("0.1")])).kind is Kind.DECIMAL

    @pytest.mark.parametrize(
        ("values", "expected_kind"),
        [
            (["a", "b"], Kind.STRING),
            ([b"\x00", b"\x01"], Kind.BYTES),
            ([{"a": 1}, {"b": 2}], Kind.JSON),
            ([[1], [2]], Kind.JSON),
            ([uuid_module.uuid4(), uuid_module.uuid4()], Kind.UUID),
            ([dt.date(2026, 1, 1)], Kind.DATE),
            ([dt.time(9, 30)], Kind.TIME),
        ],
    )
    def test_recognises_python_values(self, values, expected_kind) -> None:
        assert infer_pw_type(pd.Series(values, dtype="object")).kind is expected_kind

    def test_a_genuinely_mixed_column_is_unknown(self) -> None:
        # Naming it STRING is how one bad row turns a numeric column into text
        # for everything downstream.
        assert infer_pw_type(pd.Series([1, "a", None])).kind is Kind.UNKNOWN

    def test_mixed_exact_and_inexact_numbers_keep_the_exact_side(self) -> None:
        series = pd.Series([Decimal("1.25"), 3], dtype="object")
        assert infer_pw_type(series).kind is Kind.DECIMAL

    def test_an_empty_column_is_unknown_not_string(self) -> None:
        # It is genuinely untyped; the next load would contradict any guess.
        assert infer_pw_type(pd.Series([None, None], dtype="object")).kind is Kind.UNKNOWN

    def test_integers_get_the_narrowest_kind_that_holds_them(self) -> None:
        assert infer_pw_type(pd.Series([1, 2, 3], dtype="object")).kind is Kind.INT8
        assert infer_pw_type(pd.Series([10**12], dtype="object")).kind is Kind.INT64

    def test_integers_beyond_64_bits_become_exact_decimals(self) -> None:
        # Not an overflowing integer, and not a float that would round them.
        inferred = infer_pw_type(pd.Series([2**70], dtype="object"))
        assert inferred.kind is Kind.DECIMAL

    def test_sampling_is_bounded(self) -> None:
        # Typing a column must not mean reading fifty million rows.
        series = pd.Series(["a"] * 50_000, dtype="object")
        assert infer_pw_type(series, sample=100).kind is Kind.STRING


class TestLegacyBridge:
    """The old vocabulary must keep working while the new one lands."""

    @pytest.mark.parametrize(
        ("series", "expected"),
        [
            (pd.Series([1, 2, 3]), "int"),
            (pd.Series([1.5]), "float"),
            (pd.Series([Decimal("1.5")]), "decimal"),
            (pd.Series([True, False]), "boolean"),
            (pd.Series(["a"]), "string"),
            (pd.Series(pd.to_datetime(["2026-01-01"])), "datetime"),
            (pd.Series([1, "a"]), "mixed"),
        ],
    )
    def test_maps_back_to_the_seven_legacy_names(self, series, expected) -> None:
        assert to_legacy_name(infer_pw_type(series)) == expected

    def test_empty_is_reported_only_when_asked(self) -> None:
        assert to_legacy_name(UNKNOWN, was_empty=True) == "empty"


class TestAgreementWithTheExistingImplementation:
    """Differential test: the new inference must not change existing answers.

    This is the pattern that has found the real bugs in this project -- predicted
    versus actual, rather than a unit test agreeing with itself.
    """

    # Deliberately includes every object-column shape. An earlier version of
    # this corpus had no Decimal case, so the bridge mapped DECIMAL to "float"
    # while the original said "decimal" -- and the test passed anyway. A
    # differential test is only as good as the inputs it differs over.
    CORPUS = [
        pd.Series([Decimal("1.5")], dtype="object"),
        pd.Series([Decimal("1.5"), Decimal("2.25")], dtype="object"),
        pd.Series([uuid_module.uuid4()], dtype="object"),
        pd.Series([dt.date(2026, 1, 1)], dtype="object"),
        pd.Series([dt.time(9, 30)], dtype="object"),
        pd.Series([b"x"], dtype="object"),
        pd.Series([dt.datetime(2026, 1, 1)], dtype="object"),
        pd.Series(["a"], dtype="object"),
        pd.Series([True], dtype="object"),
        pd.Series([1], dtype="object"),
        pd.Series([1, 2, 3]),
        pd.Series([1, 2, 3], dtype="int32"),
        pd.Series([1.5, 2.5]),
        pd.Series([1.5, None]),
        pd.Series([True, False]),
        pd.Series([True, None], dtype="object"),
        pd.Series(["a", "b"]),
        pd.Series(["a", None]),
        pd.Series(pd.to_datetime(["2026-01-01", "2026-02-01"])),
        pd.Series(pd.to_datetime(["2026-01-01"], utc=True)),
        pd.Series([1, "a"]),
        pd.Series([1, 2.5], dtype="object"),
        pd.Series([], dtype="object"),
        pd.Series([None, None], dtype="object"),
        pd.Series([1, None, 3]),
    ]

    @pytest.mark.parametrize("series", CORPUS, ids=lambda s: f"{s.dtype}:{len(s)}")
    def test_legacy_name_matches_the_original_function(self, series: pd.Series) -> None:
        from service_transformations.tabular import infer_series_type

        expected = infer_series_type(series)
        was_empty = series.dropna().empty
        actual = to_legacy_name(infer_pw_type(series), was_empty=was_empty)
        assert actual == expected, (
            f"dtype={series.dtype} values={list(series[:4])}: "
            f"legacy said {expected!r}, lattice said {actual!r}"
        )

    def test_json_is_the_one_known_divergence(self) -> None:
        # The lattice has a single JSON kind; the original returns "dict" or
        # "list" depending on the values. A type alone cannot recover which, so
        # this is documented rather than silently papered over.
        from service_transformations.tabular import infer_series_type

        listy = pd.Series([[1], [2]], dtype="object")
        assert infer_series_type(listy) == "list"
        assert to_legacy_name(infer_pw_type(listy)) == "dict"
