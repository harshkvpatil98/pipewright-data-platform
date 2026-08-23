from __future__ import annotations

import pandas as pd
import pytest

from service_transformations.expressions import MAX_EXPRESSION_LENGTH, evaluate_expression
from shared_python.errors import BadRequestError


@pytest.fixture()
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "price": [10.0, 20.0, 30.0],
            "quantity": [1, 2, 3],
            "name": ["  Alpha ", "beta", None],
            "discount": [None, 5.0, None],
        }
    )


def test_arithmetic_is_vectorised(frame: pd.DataFrame) -> None:
    result, referenced = evaluate_expression(frame, "price * quantity")
    assert result.tolist() == [10.0, 40.0, 90.0]
    assert referenced == {"price", "quantity"}


def test_round_and_nested_calls(frame: pd.DataFrame) -> None:
    # round() follows NumPy/pandas half-to-even ("banker's") rounding, so an exact
    # .825 rounds down to .82 rather than up. Documented here so the behaviour is
    # a decision rather than a surprise.
    result, _ = evaluate_expression(frame, "round(price * 1.0825, 2)")
    assert result.tolist() == [10.82, 21.65, 32.48]


def test_string_functions(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "upper(trim(name))")
    assert result.tolist()[:2] == ["ALPHA", "BETA"]


def test_coalesce_fills_nulls(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "coalesce(discount, 0)")
    assert result.tolist() == [0.0, 5.0, 0.0]


def test_conditional_expression(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "'big' if price > 15 else 'small'")
    assert result.tolist() == ["small", "big", "big"]


def test_comparison_returns_boolean_series(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "price > 15")
    assert result.tolist() == [False, True, True]


def test_boolean_operators(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "(price > 5) and (quantity < 3)")
    assert result.tolist() == [True, True, False]


def test_is_null_helper(frame: pd.DataFrame) -> None:
    result, _ = evaluate_expression(frame, "is_null(discount)")
    assert result.tolist() == [True, False, True]


def test_scalar_expression_is_broadcast(frame: pd.DataFrame) -> None:
    result, referenced = evaluate_expression(frame, "42")
    assert result.tolist() == [42, 42, 42]
    assert referenced == set()


def test_unknown_column_is_rejected(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="Unknown column 'missing'"):
        evaluate_expression(frame, "missing + 1")


def test_unknown_function_is_rejected(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="Unknown function"):
        evaluate_expression(frame, "explode(price)")


# --- the security surface: none of these may execute -------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "price.__class__.__mro__",
        "[x for x in range(10)]",
        "(lambda: 1)()",
        "price[0]",
        "eval('1+1')",
        "globals()",
        "price.apply(print)",
        "{'a': 1}",
    ],
)
def test_dangerous_expressions_are_rejected(frame: pd.DataFrame, expression: str) -> None:
    with pytest.raises(BadRequestError):
        evaluate_expression(frame, expression)


def test_attribute_access_is_unreachable(frame: pd.DataFrame) -> None:
    """Attribute access is not in the allowlist, so dunder traversal cannot start."""
    with pytest.raises(BadRequestError, match="unsupported construct|Unknown"):
        evaluate_expression(frame, "name.upper")


def test_assignment_is_a_syntax_error_not_an_execution(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="not valid"):
        evaluate_expression(frame, "price = 5")


def test_empty_expression_is_rejected(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="empty"):
        evaluate_expression(frame, "   ")


def test_overlong_expression_is_rejected(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="too long"):
        evaluate_expression(frame, "price + " * MAX_EXPRESSION_LENGTH)


def test_chained_comparison_is_rejected_with_guidance(frame: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="Chained comparisons"):
        evaluate_expression(frame, "1 < price < 100")
