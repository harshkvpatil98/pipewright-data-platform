"""Deriving a column from a spreadsheet formula.

The step accepts two languages: the original `expression` syntax, which every
saved pipeline uses, and the new `formula` syntax. Both must keep working, and
the step must never guess which one it was handed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError
from service_transformations.steps.derive_column import (
    apply_derive_column,
    validate_derive_column,
)

FRAME = pd.DataFrame(
    {
        "price": [10.0, 20.0, None],
        "qty": [3, 7, 2],
        "name": ["ada", "  bob  ", None],
    }
)


def applied(config: dict) -> tuple[pd.DataFrame, list[str]]:
    return apply_derive_column(FRAME, config)


class TestFormulaColumns:
    def test_arithmetic(self) -> None:
        out, _ = applied({"target_column": "total", "formula": "=ROUND([price] * [qty], 2)"})
        assert list(out["total"])[:2] == [30.0, 140.0]

    def test_conditional(self) -> None:
        out, _ = applied({"target_column": "band", "formula": 'IF([qty] > 5, "many", "few")'})
        assert list(out["band"]) == ["few", "many", "few"]

    def test_text_manipulation(self) -> None:
        out, _ = applied({"target_column": "clean", "formula": "UPPER(TRIM([name]))"})
        assert list(out["clean"])[:2] == ["ADA", "BOB"]

    def test_a_null_input_gives_a_null_result(self) -> None:
        out, _ = applied({"target_column": "total", "formula": "[price] * [qty]"})
        assert pd.isna(list(out["total"])[2])

    def test_the_new_column_is_appended(self) -> None:
        out, _ = applied({"target_column": "total", "formula": "[qty] * 2"})
        assert list(out.columns)[-1] == "total"
        assert len(out.columns) == len(FRAME.columns) + 1


class TestBothLanguagesKeepWorking:
    def test_the_original_expression_syntax_is_unchanged(self) -> None:
        # Every saved pipeline uses it.
        out, _ = applied({"target_column": "legacy", "expression": "price * qty"})
        assert list(out["legacy"])[:2] == [30.0, 140.0]

    def test_giving_both_is_refused_rather_than_guessed(self) -> None:
        # They are different languages; picking one would eventually compute
        # something other than what was written.
        with pytest.raises(BadRequestError, match="not both"):
            validate_derive_column(FRAME, {
                "target_column": "x", "expression": "qty * 2", "formula": "[qty] * 2",
            })

    def test_giving_neither_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="required"):
            validate_derive_column(FRAME, {"target_column": "x"})


class TestValidationHappensEarly:
    def test_a_bad_column_is_caught_at_validation(self) -> None:
        # Not on row four million.
        with pytest.raises(BadRequestError, match="no column called"):
            validate_derive_column(FRAME, {"target_column": "x", "formula": "[nope] * 2"})

    def test_a_bad_function_is_caught_at_validation(self) -> None:
        with pytest.raises(BadRequestError, match="no function called"):
            validate_derive_column(FRAME, {"target_column": "x", "formula": "NOPE([qty])"})

    def test_bad_syntax_is_caught_at_validation(self) -> None:
        with pytest.raises(BadRequestError, match="position"):
            validate_derive_column(FRAME, {"target_column": "x", "formula": "[qty] *"})

    def test_overwriting_needs_permission(self) -> None:
        with pytest.raises(BadRequestError, match="already exists"):
            validate_derive_column(FRAME, {"target_column": "qty", "formula": "[qty] * 2"})

    def test_overwrite_is_allowed_when_asked_for(self) -> None:
        out, _ = applied({"target_column": "qty", "formula": "[qty] * 2", "overwrite": True})
        assert list(out["qty"]) == [6, 14, 4]


class TestBadRowsAreCountedNotFatal:
    """A bad row must not fail a ten-million-row run."""

    def test_unconvertible_rows_are_reported_with_a_count(self) -> None:
        _, warnings = applied({"target_column": "n", "formula": "VALUE([name])"})
        assert any("could not be computed for 2" in w for w in warnings)

    def test_the_count_is_against_rows_that_had_values(self) -> None:
        # "The other 1 were fine" was wrong: that row's input was empty, so it
        # was never a candidate. The denominator is the eligible rows.
        _, warnings = applied({"target_column": "n", "formula": "VALUE([name])"})
        assert any("of the 2 row(s) that had values" in w for w in warnings)

    def test_a_clean_formula_warns_about_nothing(self) -> None:
        _, warnings = applied({"target_column": "t", "formula": "[qty] * 2"})
        assert warnings == []

    def test_a_constant_formula_says_so(self) -> None:
        _, warnings = applied({"target_column": "k", "formula": "42"})
        assert any("every row gets the same value" in w for w in warnings)

    def test_a_formula_whose_inputs_are_all_missing_says_that_instead(self) -> None:
        frame = pd.DataFrame({"a": [None, None], "b": [1, 2]})
        _, warnings = apply_derive_column(
            frame, {"target_column": "c", "formula": "[a] * 2"}
        )
        assert any("Every row is missing a value" in w for w in warnings)


class TestFormulasPushDown:
    """The payoff for parsing formulas into IR rather than a private AST.

    `=UPPER([name])` becomes a projection and runs at the source, instead of
    pulling the column across the network to compute it here.
    """

    def _scan(self):
        from service_transformations.ir.nodes import Scan
        from shared_python.types import FLOAT64, STRING

        return Scan("orders", (("name", STRING), ("amount", FLOAT64)))

    def test_a_formula_becomes_a_projection(self) -> None:
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.nodes import Project

        node = compile_step(
            self._scan(), "derive_column", {"target_column": "shout", "formula": "UPPER([name])"}
        )
        assert isinstance(node, Project)

    def test_a_pushable_formula_reaches_the_source(self) -> None:
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.planner import plan

        node = compile_step(
            self._scan(), "derive_column", {"target_column": "shout", "formula": "UPPER([name])"}
        )
        assert plan(node, "postgres").local_count == 0

    def test_a_regex_formula_stays_local(self) -> None:
        # There is no portable SQL spelling for a regex, so pushing it as LIKE
        # would be a different computation wearing the same name.
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.planner import plan

        node = compile_step(
            self._scan(),
            "derive_column",
            {"target_column": "x", "formula": "REGEXEXTRACT([name], '(a)')"},
        )
        assert plan(node, "postgres").local_count == 1

    def test_the_new_column_appears_in_the_schema(self) -> None:
        from service_transformations.ir.from_steps import compile_step

        node = compile_step(
            self._scan(), "derive_column", {"target_column": "shout", "formula": "UPPER([name])"}
        )
        assert "shout" in node.schema()
        assert list(node.schema()) == ["name", "amount", "shout"]

    def test_overwriting_replaces_in_place_rather_than_appending(self) -> None:
        from service_transformations.ir.from_steps import compile_step

        node = compile_step(
            self._scan(),
            "derive_column",
            {"target_column": "name", "formula": "UPPER([name])", "overwrite": True},
        )
        assert list(node.schema()) == ["name", "amount"]

    def test_the_legacy_syntax_remains_an_extension(self) -> None:
        # It has its own evaluator and runs identically; it simply does not
        # push down, and saying so is better than pretending it does.
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.nodes import Extension

        node = compile_step(
            self._scan(), "derive_column", {"target_column": "y", "expression": "amount * 2"}
        )
        assert isinstance(node, Extension)

    def test_an_unparseable_formula_does_not_break_planning(self) -> None:
        # The step's own validation gives a far better message; planning must
        # not raise on its way to producing one.
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.nodes import Extension

        node = compile_step(
            self._scan(), "derive_column", {"target_column": "y", "formula": "UPPER("}
        )
        assert isinstance(node, Extension)

    def test_conversions_stay_local_because_they_render_differently(self) -> None:
        # `CAST(1.0 AS TEXT)` is "1.0" in Postgres where this renders "1", and a
        # failed numeric cast raises in SQL where this yields null. Pushing them
        # would make the answer depend on where the query ran.
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.planner import plan

        for formula in ("TEXT([amount])", "VALUE([name])"):
            node = compile_step(
                self._scan(), "derive_column", {"target_column": "x", "formula": formula}
            )
            assert plan(node, "postgres").local_count == 1, formula

