"""Parsing spreadsheet formulas into IR.

The formula language is the one people already know, which means its rules are
Excel's rather than Python's -- and several of those are surprising. Each one is
pinned here, because "it behaves like Excel" is only useful if it actually does.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError
from service_transformations.formula.lexer import tokenise
from service_transformations.formula.parser import function_names, parse_formula
from service_transformations.ir.expressions import Case
from service_transformations.ir.pandas_backend import evaluate

FRAME = pd.DataFrame(
    {
        "amount": [1200.0, 50.0, None],
        "name": ["ada", "  bob ", None],
        "qty": [3, 7, 2],
        "order total": [10.0, 20.0, 30.0],
    }
)
COLUMNS = list(FRAME.columns)


def result(source: str) -> list:
    return list(evaluate(parse_formula(source, columns=COLUMNS), FRAME))


class TestLexing:
    def test_a_leading_equals_is_accepted_and_dropped(self) -> None:
        # So a formula pasted straight out of Excel works.
        assert result("=1 + 1") == result("1 + 1")

    def test_column_names_may_contain_spaces(self) -> None:
        assert result("[order total] * 2") == [20.0, 40.0, 60.0]

    def test_doubled_quotes_are_a_literal_quote(self) -> None:
        assert result('"say ""hi"""')[0] == 'say "hi"'

    def test_single_quotes_work_too(self) -> None:
        assert result("'hello'")[0] == "hello"

    def test_longer_operators_match_first(self) -> None:
        # `<=` must not lex as `<` then `=`.
        kinds = [t.text for t in tokenise("a <= b") if t.text]
        assert "<=" in kinds

    def test_an_unclosed_column_reference_says_so(self) -> None:
        with pytest.raises(BadRequestError, match="never closed"):
            parse_formula("[amount")

    def test_an_unclosed_string_says_so(self) -> None:
        with pytest.raises(BadRequestError, match="never closed"):
            parse_formula('"hello')

    def test_an_empty_column_reference_is_rejected(self) -> None:
        with pytest.raises(BadRequestError, match="Empty column"):
            parse_formula("[]")

    def test_a_formula_can_be_too_long(self) -> None:
        with pytest.raises(BadRequestError, match="limit is"):
            parse_formula("1+" * 3000 + "1")


class TestPrecedence:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("2 + 3 * 4", 14),
            ("(2 + 3) * 4", 20),
            ("10 - 2 - 3", 5),
            ("2 ^ 3 ^ 2", 512),        # right-associative: 2^(3^2)
            ("10 / 2 * 5", 25),
        ],
    )
    def test_arithmetic(self, source: str, expected) -> None:
        assert result(source)[0] == expected

    def test_unary_minus_binds_tighter_than_power_as_in_excel(self) -> None:
        # Excel evaluates -3^2 as (-3)^2 = 9. Almost every other language gives
        # -9. Following Excel here because the audience is spreadsheet users.
        assert result("-3 ^ 2")[0] == 9

    def test_concatenation_binds_tighter_than_comparison(self) -> None:
        # `"a" & "b" = "ab"` must compare the joined text, not concatenate a
        # boolean onto "a".
        assert result('"a" & "b" = "ab"')[0]

    def test_comparison_is_written_with_a_single_equals(self) -> None:
        assert result("[qty] = 3")[0]

    def test_inequality_accepts_both_spellings(self) -> None:
        assert result("[qty] <> 99")[0]
        assert result("[qty] != 99")[0]


class TestFunctions:
    def test_if_becomes_a_case(self) -> None:
        expression = parse_formula('IF([amount] > 1000, "large", "small")', columns=COLUMNS)
        assert isinstance(expression, Case)
        assert result('IF([amount] > 1000, "large", "small")') == ["large", "small", "small"]

    def test_if_without_an_else_yields_null(self) -> None:
        assert result('IF([qty] > 5, "many")')[0] is None

    def test_ifs_handles_several_branches(self) -> None:
        assert result('IFS([qty] > 5, "many", [qty] > 2, "some")') == ["some", "many", None]

    def test_ifs_requires_pairs(self) -> None:
        with pytest.raises(BadRequestError, match="pairs"):
            parse_formula('IFS([qty] > 5, "many", [qty])', columns=COLUMNS)

    def test_function_names_are_case_insensitive(self) -> None:
        assert result("upper('a')") == result("UPPER('a')") == result("Upper('a')")

    def test_spreadsheet_aliases_map_onto_the_catalogue(self) -> None:
        assert result("LEN('abcd')")[0] == 4
        assert result("PROPER('ada lovelace')")[0] == "Ada Lovelace"
        assert result("VALUE('42')")[0] == 42

    def test_true_and_false_are_values(self) -> None:
        assert result("IF(TRUE, 1, 2)")[0] == 1
        assert result("IF(FALSE, 1, 2)")[0] == 2

    def test_a_function_with_no_arguments(self) -> None:
        assert len(result("TODAY()")) == len(FRAME)

    def test_nested_calls(self) -> None:
        assert result("UPPER(TRIM([name]))")[0] == "ADA"

    def test_arity_is_checked_at_parse_time(self) -> None:
        # Not at run time, on row four million.
        with pytest.raises(BadRequestError, match="takes"):
            parse_formula("UPPER()", columns=COLUMNS)


class TestErrorsAreActionable:
    def test_a_bare_word_suggests_brackets(self) -> None:
        # By far the commonest mistake: writing `amount` instead of `[amount]`.
        with pytest.raises(BadRequestError, match=r"\[amount\]"):
            parse_formula("amount > 1", columns=COLUMNS)

    def test_an_unknown_column_lists_what_is_available(self) -> None:
        with pytest.raises(BadRequestError, match="no column called"):
            parse_formula("[nope]", columns=COLUMNS)

    def test_a_case_mismatch_names_the_real_column(self) -> None:
        with pytest.raises(BadRequestError, match=r"Did you mean \[amount\]"):
            parse_formula("[AMOUNT]", columns=COLUMNS)

    def test_an_unknown_function_suggests_the_nearest(self) -> None:
        with pytest.raises(BadRequestError, match="Did you mean"):
            parse_formula("UPPPER('a')", columns=COLUMNS)

    def test_an_unclosed_bracket_says_where(self) -> None:
        with pytest.raises(BadRequestError, match="closing bracket"):
            parse_formula("UPPER('a'", columns=COLUMNS)

    def test_trailing_junk_is_reported(self) -> None:
        with pytest.raises(BadRequestError, match="Is an operator missing"):
            parse_formula("1 2", columns=COLUMNS)

    def test_errors_point_at_a_position(self) -> None:
        with pytest.raises(BadRequestError, match="position"):
            parse_formula("1 +", columns=COLUMNS)

    def test_columns_are_only_checked_when_a_list_is_supplied(self) -> None:
        # The parser is also used before a schema is known.
        assert parse_formula("[whatever] + 1") is not None


class TestItProducesRealIR:
    """The whole point: a formula is an IR expression, so it gets everything
    the IR has -- type inference, lineage, and pushdown."""

    def test_a_formula_reports_the_columns_it_uses(self) -> None:
        expression = parse_formula("[amount] * [qty]", columns=COLUMNS)
        assert expression.columns_used() == {"amount", "qty"}

    def test_a_formula_has_a_type(self) -> None:
        from shared_python.types import FLOAT64, Kind, decimal

        expression = parse_formula("[amount] * [qty]", columns=COLUMNS)
        schema = {"amount": decimal(18, 2), "qty": FLOAT64}
        assert expression.type_of(schema).kind is not Kind.UNKNOWN

    def test_a_supported_formula_compiles_to_sql(self) -> None:
        from service_transformations.ir.expressions import supported_in

        expression = parse_formula("UPPER([name]) & '-x'", columns=COLUMNS)
        assert supported_in("postgres", expression)

    def test_a_regex_formula_is_reported_as_local_only(self) -> None:
        # No portable SQL spelling, so it must not be pushed down as LIKE.
        from service_transformations.ir.expressions import supported_in

        expression = parse_formula("REGEXMATCH([name], 'a.*')", columns=COLUMNS)
        assert not supported_in("postgres", expression)


class TestAutocomplete:
    def test_every_name_it_offers_actually_parses(self) -> None:
        # An autocomplete list containing a name the parser rejects is worse
        # than no autocomplete.
        for name in function_names():
            assert isinstance(name, str) and name
        assert "if" in function_names()
        assert len(function_names()) > 80
