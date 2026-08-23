"""Safe, vectorised expression evaluation for derived columns.

Operators author expressions like ``round(price * quantity, 2)`` or
``upper(trim(name))``. These are parsed into a Python AST and walked against an
explicit allowlist of node types and functions -- ``eval`` is never called on
operator input, and attribute access, subscripting, comprehensions, lambdas, and
every builtin are unreachable by construction.

Evaluation is vectorised: identifiers resolve to pandas Series, so an expression
runs once over the whole column rather than row by row.
"""

from __future__ import annotations

import ast
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError

MAX_EXPRESSION_LENGTH = 2_000


def _as_series(value: Any, index: pd.Index) -> pd.Series:
    """Broadcast a scalar to a Series so mixed scalar/column operands align."""
    if isinstance(value, pd.Series):
        return value
    return pd.Series([value] * len(index), index=index)


def _coalesce(*values: Any) -> Any:
    if not values:
        raise BadRequestError("coalesce() requires at least one argument.")
    result = values[0]
    for candidate in values[1:]:
        if isinstance(result, pd.Series):
            result = result.where(result.notna(), candidate)
        elif result is None or (isinstance(result, float) and math.isnan(result)):
            result = candidate
    return result


def _concat(*values: Any) -> Any:
    if not values:
        return ""
    series_args = [v for v in values if isinstance(v, pd.Series)]
    if not series_args:
        return "".join("" if v is None else str(v) for v in values)
    index = series_args[0].index
    out = pd.Series([""] * len(index), index=index)
    for value in values:
        part = _as_series(value, index) if not isinstance(value, pd.Series) else value
        out = out.str.cat(part.fillna("").astype(str))
    return out


def _string_method(name: str) -> Callable[[Any], Any]:
    def apply(value: Any) -> Any:
        if isinstance(value, pd.Series):
            return getattr(value.astype("string").str, name)()
        return getattr(str(value), name)() if value is not None else None

    return apply


def _numeric(func: Callable[[Any], Any], np_func: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def apply(value: Any) -> Any:
        if isinstance(value, pd.Series):
            return np_func(pd.to_numeric(value, errors="coerce"))
        return func(value)

    return apply


def _round(value: Any, digits: Any = 0) -> Any:
    ndigits = int(digits) if not isinstance(digits, pd.Series) else 0
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce").round(ndigits)
    return round(float(value), ndigits)


def _is_null(value: Any) -> Any:
    return value.isna() if isinstance(value, pd.Series) else value is None


def _length(value: Any) -> Any:
    if isinstance(value, pd.Series):
        return value.astype("string").str.len()
    return len(str(value)) if value is not None else None


def _abs(value: Any) -> Any:
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce").abs()
    return abs(value)


def _min(*values: Any) -> Any:
    return _reduce_pairwise(values, lambda a, b: np.minimum(a, b), min)


def _max(*values: Any) -> Any:
    return _reduce_pairwise(values, lambda a, b: np.maximum(a, b), max)


def _reduce_pairwise(values: tuple[Any, ...], vector_op: Callable, scalar_op: Callable) -> Any:
    if not values:
        raise BadRequestError("min()/max() require at least one argument.")
    result = values[0]
    for candidate in values[1:]:
        if isinstance(result, pd.Series) or isinstance(candidate, pd.Series):
            result = vector_op(result, candidate)
        else:
            result = scalar_op(result, candidate)
    return result


ALLOWED_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": _abs,
    "round": _round,
    "min": _min,
    "max": _max,
    "length": _length,
    "upper": _string_method("upper"),
    "lower": _string_method("lower"),
    "trim": _string_method("strip"),
    "coalesce": _coalesce,
    "concat": _concat,
    "is_null": _is_null,
    "floor": _numeric(math.floor, np.floor),
    "ceil": _numeric(math.ceil, np.ceil),
    "sqrt": _numeric(math.sqrt, np.sqrt),
}

# Bare names that are literals rather than column references.
_RESERVED_NAMES = frozenset({"true", "false", "null", "none"})

_ALLOWED_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_ALLOWED_COMPARE: dict[type, Callable[[Any, Any], Any]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


class _ExpressionEvaluator(ast.NodeVisitor):
    def __init__(self, dataframe: pd.DataFrame) -> None:
        self.dataframe = dataframe
        self.referenced_columns: set[str] = set()

    def generic_visit(self, node: ast.AST) -> Any:  # noqa: D102 - allowlist gate
        raise BadRequestError(
            f"Expression contains an unsupported construct ({type(node).__name__}). "
            "Allowed: column names, numbers, strings, arithmetic, comparisons, and approved functions."
        )

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise BadRequestError("Only number, string, boolean, and null literals are allowed.")

    def visit_Name(self, node: ast.Name) -> Any:
        column = node.id
        if column in self.dataframe.columns:
            self.referenced_columns.add(column)
            return self.dataframe[column]
        if column.lower() in {"true", "false"}:
            return column.lower() == "true"
        if column.lower() in _RESERVED_NAMES:
            return None
        raise BadRequestError(f"Unknown column '{column}' referenced in expression.")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        handler = _ALLOWED_BINOPS.get(type(node.op))
        if handler is None:
            raise BadRequestError(f"Unsupported operator '{type(node.op).__name__}' in expression.")
        left, right = self.visit(node.left), self.visit(node.right)
        try:
            return handler(left, right)
        except (TypeError, ValueError) as exc:
            raise BadRequestError(f"Expression could not be evaluated: {exc}") from exc

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return ~operand if isinstance(operand, pd.Series) else (not operand)
        raise BadRequestError("Unsupported unary operator in expression.")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [self.visit(value) for value in node.values]
        result = values[0]
        for candidate in values[1:]:
            if isinstance(node.op, ast.And):
                result = (result & candidate) if isinstance(result, pd.Series) else (result and candidate)
            else:
                result = (result | candidate) if isinstance(result, pd.Series) else (result or candidate)
        return result

    def visit_Compare(self, node: ast.Compare) -> Any:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise BadRequestError("Chained comparisons are not supported; combine them with 'and'.")
        handler = _ALLOWED_COMPARE.get(type(node.ops[0]))
        if handler is None:
            raise BadRequestError("Unsupported comparison operator in expression.")
        return handler(self.visit(node.left), self.visit(node.comparators[0]))

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        condition = self.visit(node.test)
        if_true, if_false = self.visit(node.body), self.visit(node.orelse)
        if isinstance(condition, pd.Series):
            index = condition.index
            return _as_series(if_true, index).where(condition, _as_series(if_false, index))
        return if_true if condition else if_false

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise BadRequestError("Only direct calls to approved functions are allowed.")
        function = ALLOWED_FUNCTIONS.get(node.func.id)
        if function is None:
            raise BadRequestError(
                f"Unknown function '{node.func.id}'. Available: {', '.join(sorted(ALLOWED_FUNCTIONS))}."
            )
        if node.keywords:
            raise BadRequestError("Keyword arguments are not supported in expressions.")
        arguments = [self.visit(argument) for argument in node.args]
        try:
            return function(*arguments)
        except BadRequestError:
            raise
        except (TypeError, ValueError) as exc:
            raise BadRequestError(f"{node.func.id}() could not be evaluated: {exc}") from exc


def evaluate_expression(dataframe: pd.DataFrame, expression: str) -> tuple[pd.Series, set[str]]:
    """Evaluate `expression` against `dataframe`, returning the result and columns used."""
    if not isinstance(expression, str) or not expression.strip():
        raise BadRequestError("Expression cannot be empty.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise BadRequestError(f"Expression is too long (limit {MAX_EXPRESSION_LENGTH} characters).")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise BadRequestError(f"Expression is not valid: {exc.msg}.") from exc

    evaluator = _ExpressionEvaluator(dataframe)
    result = evaluator.visit(tree)

    if not isinstance(result, pd.Series):
        result = _as_series(result, dataframe.index)
    return result, evaluator.referenced_columns


def referenced_columns(expression: str) -> set[str]:
    """The column names an expression reads, derived without touching data.

    Lineage has to answer "what does this expression depend on" before any run
    exists, so it cannot go through :func:`evaluate_expression`, which resolves
    names against a real frame. Both must agree on what counts as a column
    reference: a bare name that is neither a literal nor the target of a call.

    An unparseable expression yields no references rather than raising -- the
    step's own validation is where a bad expression should be reported, and a
    lineage graph that omits one edge is better than one that cannot be drawn.
    """
    if not isinstance(expression, str) or not expression.strip():
        return set()

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        return set()

    function_names = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and id(node) not in function_names
        and node.id.lower() not in _RESERVED_NAMES
    }
