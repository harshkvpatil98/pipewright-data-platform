"""Every function in the catalogue, exercised with real values.

One catalogue serves both the IR and the formula language, so a function that
compiles but has no pandas implementation is a formula that parses and then
fails at run time. These give each function arguments of the right shape and
check the answer, not merely that it did not raise.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.expressions import FUNCTIONS, Call, Column, Literal
from service_transformations.ir.pandas_backend import evaluate

FRAME = pd.DataFrame(
    {
        "text": ["hello world", "  padded  ", "Alpha-Beta-Gamma", None],
        "num": [4.0, -9.0, 2.5, None],
        "whole": [10, 3, 7, None],
        "when": pd.to_datetime(["2026-01-15", "2026-03-01", "2026-12-31", None]),
        "flag": [True, False, True, None],
    }
)

TEXT, NUM, WHOLE, WHEN = Column("text"), Column("num"), Column("whole"), Column("when")


def value_at(expression, row: int):
    return evaluate(expression, FRAME).iloc[row]


class TestMaths:
    @pytest.mark.parametrize(
        ("call", "row", "expected"),
        [
            (Call("abs", (NUM,)), 1, 9.0),
            (Call("sqrt", (Call("abs", (NUM,)),)), 0, 2.0),
            (Call("sign", (NUM,)), 1, -1),
            (Call("power", (NUM, Literal(2, INT64))), 0, 16.0),
            (Call("trunc", (NUM,)), 2, 2),
            (Call("floor", (NUM,)), 2, 2),
            (Call("ceil", (NUM,)), 2, 3),
            (Call("round", (NUM, Literal(0, INT64))), 2, 2.0),
            (Call("mod", (WHOLE, Literal(3, INT64))), 0, 1),
            (Call("greatest", (NUM, Literal(3.0, FLOAT64))), 1, 3.0),
            (Call("least", (NUM, Literal(3.0, FLOAT64))), 0, 3.0),
        ],
    )
    def test_numeric_functions(self, call, row, expected) -> None:
        assert value_at(call, row) == expected

    def test_log_of_a_non_positive_number_is_null_not_infinity(self) -> None:
        # -inf in a numeric column poisons every later sum and average.
        assert pd.isna(value_at(Call("ln", (Literal(0.0, FLOAT64),)), 0))

    def test_exp_and_ln_round_trip(self) -> None:
        result = value_at(Call("ln", (Call("exp", (Literal(2.0, FLOAT64),)),)), 0)
        assert abs(result - 2.0) < 1e-9


class TestText:
    @pytest.mark.parametrize(
        ("call", "row", "expected"),
        [
            (Call("upper", (TEXT,)), 0, "HELLO WORLD"),
            (Call("lower", (TEXT,)), 2, "alpha-beta-gamma"),
            (Call("trim", (TEXT,)), 1, "padded"),
            (Call("ltrim", (TEXT,)), 1, "padded  "),
            (Call("rtrim", (TEXT,)), 1, "  padded"),
            (Call("length", (TEXT,)), 0, 11),
            (Call("left", (TEXT, Literal(5, INT64))), 0, "hello"),
            (Call("right", (TEXT, Literal(5, INT64))), 0, "world"),
            (Call("reverse", (Literal("abc", STRING),)), 0, "cba"),
            (Call("repeat", (Literal("ab", STRING), Literal(3, INT64))), 0, "ababab"),
            (Call("initcap", (TEXT,)), 0, "Hello World"),
            (Call("replace", (TEXT, Literal("world", STRING), Literal("there", STRING))), 0, "hello there"),
            (Call("substring", (TEXT, Literal(1, INT64), Literal(5, INT64))), 0, "hello"),
            (Call("split_part", (TEXT, Literal("-", STRING), Literal(2, INT64))), 2, "Beta"),
        ],
    )
    def test_text_functions(self, call, row, expected) -> None:
        assert value_at(call, row) == expected

    def test_position_is_one_based_like_sql(self) -> None:
        # 1-based, and 0 for not found -- matching SQL and every spreadsheet.
        assert value_at(Call("position", (TEXT, Literal("world", STRING))), 0) == 7
        assert value_at(Call("position", (TEXT, Literal("zzz", STRING))), 0) == 0

    @pytest.mark.parametrize(
        ("call", "expected"),
        [
            (Call("starts_with", (TEXT, Literal("hello", STRING))), True),
            (Call("ends_with", (TEXT, Literal("world", STRING))), True),
            (Call("contains", (TEXT, Literal("lo wo", STRING))), True),
            (Call("contains", (TEXT, Literal("zzz", STRING))), False),
        ],
    )
    def test_predicates(self, call, expected) -> None:
        assert bool(value_at(call, 0)) is expected

    def test_lpad_and_rpad(self) -> None:
        assert value_at(Call("lpad", (Literal("7", STRING), Literal(3, INT64), Literal("0", STRING))), 0) == "007"
        assert value_at(Call("rpad", (Literal("7", STRING), Literal(3, INT64), Literal("0", STRING))), 0) == "700"

    def test_regex_functions(self) -> None:
        assert value_at(Call("regex_match", (TEXT, Literal(r"^hello", STRING))), 0)
        assert (
            value_at(Call("regex_extract", (TEXT, Literal(r"(\w+)-(\w+)", STRING))), 2)
            == "Alpha"
        )
        assert (
            value_at(Call("regex_replace", (TEXT, Literal(r"\s+", STRING), Literal("_", STRING))), 0)
            == "hello_world"
        )

    def test_concat_joins_several_arguments(self) -> None:
        call = Call("concat", (Literal("a", STRING), Literal("-", STRING), Literal("b", STRING)))
        assert value_at(call, 0) == "a-b"


class TestTemporal:
    @pytest.mark.parametrize(
        ("call", "row", "expected"),
        [
            (Call("year", (WHEN,)), 0, 2026),
            (Call("month", (WHEN,)), 1, 3),
            (Call("day", (WHEN,)), 0, 15),
            (Call("quarter", (WHEN,)), 2, 4),
        ],
    )
    def test_extraction(self, call, row, expected) -> None:
        assert value_at(call, row) == expected

    def test_day_of_week_is_iso_with_monday_as_one(self) -> None:
        # Stated because every system numbers this differently, and a report
        # that is off by one day is very hard to spot.
        assert value_at(Call("day_of_week", (WHEN,)), 0) == 4  # 2026-01-15 is a Thursday

    def test_days_between_counts_forwards(self) -> None:
        call = Call("days_between", (WHEN, Call("add_days", (WHEN, Literal(10, INT64)))))
        assert value_at(call, 0) == 10

    def test_add_days_moves_the_date(self) -> None:
        assert value_at(Call("add_days", (WHEN, Literal(1, INT64))), 0) == pd.Timestamp("2026-01-16")

    def test_now_and_today_produce_one_value_per_row(self) -> None:
        assert len(evaluate(Call("now", ()), FRAME)) == len(FRAME)
        assert len(evaluate(Call("today", ()), FRAME)) == len(FRAME)


class TestTypesAndInformation:
    def test_to_number_coerces_and_nulls_the_rest(self) -> None:
        assert value_at(Call("to_number", (Literal("42", STRING),)), 0) == 42
        assert pd.isna(value_at(Call("to_number", (TEXT,)), 0))

    def test_to_text_renders(self) -> None:
        assert value_at(Call("to_text", (WHOLE,)), 0) == "10"

    def test_is_number_and_is_text(self) -> None:
        assert bool(value_at(Call("is_number", (WHOLE,)), 0))
        assert not bool(value_at(Call("is_number", (TEXT,)), 0))
        assert bool(value_at(Call("is_text", (TEXT,)), 0))

    def test_if_error_supplies_a_fallback(self) -> None:
        # A bad row becomes the fallback rather than failing a ten-million-row run.
        call = Call("if_error", (Call("to_number", (TEXT,)), Literal(0.0, FLOAT64)))
        assert value_at(call, 0) == 0.0

    def test_nullif_blanks_a_sentinel(self) -> None:
        call = Call("nullif", (TEXT, Literal("hello world", STRING)))
        assert pd.isna(value_at(call, 0))

    def test_coalesce_takes_the_first_present_value(self) -> None:
        assert value_at(Call("coalesce", (NUM, Literal(-1.0, FLOAT64))), 3) == -1.0


class TestNullsPropagate:
    """A null in, a null out -- for every scalar function."""

    #  needs a boolean; feeding it text is a formula error, not a null
    # question, and it is covered by its own test below.
    #: Predicates *about* a value, where null is a legitimate input and the
    #: answer is true or false rather than "unknown". `is_blank(NULL)` is the
    #: whole point of `is_blank`; returning null there would make it useless.
    SKIP = {
        "now", "today", "is_number", "is_text", "coalesce", "if_error",
        "is_null", "is_not_null", "not", "is_blank", "is_date",
    }

    @pytest.mark.parametrize(
        "name",
        sorted(
            name
            for name, signature in FUNCTIONS.items()
            if not signature.is_aggregate and signature.min_args == 1 and signature.max_args == 1
        ),
    )
    def test_a_null_input_gives_a_null_output(self, name: str) -> None:
        if name in self.SKIP:
            pytest.skip(f"{name} is defined on null input")
        # Row 3 is null in every column.
        source = WHEN if name in {"year", "month", "day", "hour", "minute", "quarter", "week", "day_of_week", "to_date"} else (
            NUM if name in {"abs", "sqrt", "exp", "ln", "log10", "sign", "trunc", "floor", "ceil", "neg", "round"} else TEXT
        )
        assert pd.isna(value_at(Call(name, (source,)), 3)), f"{name} invented a value from null"


class TestErrorsAreUnderstandable:
    """A formula error must tell the person who wrote it what to change."""

    def test_a_boolean_function_on_text_says_what_to_do(self) -> None:
        from service_transformations.ir.nodes import IRError

        with pytest.raises(IRError, match="needs a true/false value"):
            evaluate(Call("not", (Column("text"),)), FRAME)

    def test_regex_extract_names_the_group_it_could_not_find(self) -> None:
        from service_transformations.ir.nodes import IRError

        with pytest.raises(IRError, match="capture group"):
            evaluate(
                Call("regex_extract", (Column("text"), Literal(r"(\w+)", STRING), Literal(9, INT64))),
                FRAME,
            )

    def test_regex_extract_handles_several_capture_groups(self) -> None:
        # `expand=False` silently returns a DataFrame with more than one group,
        # and everything downstream then receives the wrong shape.
        call = Call("regex_extract", (Column("text"), Literal(r"(\w+)-(\w+)", STRING), Literal(2, INT64)))
        assert value_at(call, 2) == "Beta"

    def test_to_text_does_not_invent_a_decimal_point(self) -> None:
        # A null makes an integer column float64, and "10.0" in a text column is
        # the kind of thing that shows up in an exported report.
        assert value_at(Call("to_text", (Column("whole"),)), 0) == "10"


class TestCatalogueIntegrity:
    def test_every_non_aggregate_function_has_a_pandas_path(self) -> None:
        # A function that compiles but cannot run is a formula that parses and
        # then fails at run time, which is the worst place to find out.
        unimplemented: list[str] = []
        for name, signature in FUNCTIONS.items():
            if signature.is_aggregate:
                continue
            args = tuple(_argument_for(name, index) for index in range(max(1, signature.min_args)))
            if signature.min_args == 0:
                args = ()
            try:
                evaluate(Call(name, args), FRAME)
            except Exception as exc:  # noqa: BLE001 - the point is to catch everything
                if "No pandas implementation" in str(exc):
                    unimplemented.append(name)
        assert unimplemented == [], f"no pandas implementation for: {unimplemented}"

    def test_every_function_declares_a_result_type(self) -> None:
        for name, signature in FUNCTIONS.items():
            assert signature.result_type([INT64, INT64]) is not None, name

    #: The functions a pipeline has to push down for pushdown to be worth
    #: having. A ratio over the whole catalogue used to stand in for this, and
    #: stopped meaning anything once the Phase 16 tool library tripled the
    #: catalogue with tools that are honestly local -- the ratio fell while the
    #: thing it was protecting was untouched.
    PUSHDOWN_CRITICAL = frozenset({
        "eq", "ne", "lt", "le", "gt", "ge", "is_null", "is_not_null", "in_list",
        "between", "and", "or", "not",
        "add", "sub", "mul", "div", "neg", "abs", "round", "floor", "ceil",
        "upper", "lower", "trim", "ltrim", "rtrim", "length", "concat",
        "substring", "left", "right", "replace", "coalesce", "nullif",
        "starts_with", "ends_with", "contains",
        "year", "month", "day", "hour", "minute", "quarter",
        "count", "count_distinct", "sum", "avg", "min", "max",
        "greatest", "least", "power", "sqrt", "exp", "ln", "log10", "sign",
    })

    def test_every_pushdown_critical_function_lowers_to_postgres(self) -> None:
        missing = sorted(
            name for name in self.PUSHDOWN_CRITICAL if "postgres" not in FUNCTIONS[name].sql
        )
        assert missing == [], f"pushdown would silently stop working for: {missing}"

    def test_the_pushdown_critical_list_names_real_functions(self) -> None:
        # Otherwise a rename turns the test above into a no-op that still passes.
        assert self.PUSHDOWN_CRITICAL <= set(FUNCTIONS)

    def test_a_lowering_that_exists_covers_the_reference_dialect(self) -> None:
        """If a function can be written in any dialect, say so for Postgres too.

        The exceptions are real: MySQL has `SOUNDEX` and `TO_BASE64` built in
        where Postgres needs an extension that may not be installed, and a
        missing-function error at run time is worse than running locally.
        """
        mysql_only = {"soundex", "base64_encode", "base64_decode", "sha1", "sha512"}
        # DuckDB has ordered-set and product aggregates that Postgres spells
        # differently enough that a naive lowering would return a different
        # number. Documented at the definitions themselves.
        duckdb_only = {"median", "product"}
        mysql_only |= duckdb_only
        offenders = sorted(
            name
            for name, signature in FUNCTIONS.items()
            if signature.sql and "postgres" not in signature.sql and name not in mysql_only
        )
        assert offenders == []


def _argument_for(name: str, index: int):
    if name in {"lpad", "rpad"}:
        return [TEXT, Literal(6, INT64), Literal("*", STRING)][index]
    if name in {"regex_match", "regex_extract"}:
        return [TEXT, Literal(r"(\w+)", STRING)][index]
    if name == "regex_replace":
        return [TEXT, Literal(r"\s", STRING), Literal("_", STRING)][index]
    if name in {"replace", "substring"}:
        return [TEXT, Literal(1, INT64), Literal(2, INT64)][index]
    if name == "split_part":
        return [TEXT, Literal("-", STRING), Literal(1, INT64)][index]
    if name in {"starts_with", "ends_with", "contains", "position", "in_list"}:
        return [TEXT, Literal("h", STRING)][index]
    if name == "date_trunc":
        return [Literal("day", STRING), WHEN][index]
    if name in {"year", "month", "day", "hour", "minute", "quarter", "week", "day_of_week", "to_date"}:
        return WHEN
    if name in {"days_between", "add_days"}:
        return [WHEN, Literal(1, INT64)][index]
    if name in {"and", "or", "not"}:
        return Call("is_not_null", (TEXT,))
    if name in {"upper", "lower", "trim", "ltrim", "rtrim", "length", "initcap", "reverse", "to_text"}:
        return TEXT
    if name in {"left", "right", "repeat"}:
        return [TEXT, Literal(2, INT64)][index]
    return [NUM, Literal(2, INT64), Literal(3, INT64)][index]
