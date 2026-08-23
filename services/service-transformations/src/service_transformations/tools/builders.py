"""Helpers for declaring tools without repeating IR plumbing.

Most tools are "replace one column with an expression over it", which in IR
terms is a `Project` that passes every other column through unchanged. Writing
that by hand two hundred times would guarantee two hundred chances to forget the
pass-through and silently drop the rest of the frame.
"""

from __future__ import annotations

from typing import Any, Callable

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING, PWType

from service_transformations.ir.expressions import Call, Case, Column, Expr, Literal
from service_transformations.ir.nodes import IRError, Node, Project

#: What a per-column tool does to one column's expression.
ColumnFn = Callable[[Expr, dict[str, Any]], Expr]


def require_column(node: Node, name: str | None) -> str:
    if not name:
        raise BadRequestError("This tool needs a column to work on.")
    if name not in node.schema():
        raise BadRequestError(
            f"Column {name!r} is not in this dataset. "
            f"Available: {', '.join(node.schema()) or 'none'}."
        )
    return name


def project_over(
    node: Node,
    column: str,
    expression: Expr,
    *,
    into: str | None = None,
) -> Project:
    """Rebuild the frame with one column replaced, or a new one appended.

    Order is preserved deliberately: a tool that quietly moved its column to the
    end would reshuffle the grid every time somebody trimmed some whitespace.
    """
    schema = node.schema()
    target = into or column
    if into and into in schema and into != column:
        raise BadRequestError(
            f"Column {into!r} already exists. Choose another name, or leave the "
            "destination empty to replace the original."
        )

    projections: list[tuple[str, Expr]] = []
    for name in schema:
        projections.append((name, expression if name == target else Column(name)))
    if target not in schema:
        projections.append((target, expression))
    return Project(input=node, projections=tuple(projections))


def column_tool(fn: ColumnFn):
    """Turn "what to do to the column" into a full ``build`` function."""

    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        expression = fn(Column(column), params)
        return project_over(node, column, expression, into=params.get("into") or None)

    return build


def call(name: str, *args: Expr) -> Call:
    return Call(name=name, args=tuple(args))


def text(value: Any) -> Literal:
    return Literal(value=value, type=STRING)


def number(value: Any) -> Literal:
    return Literal(value=value, type=FLOAT64)


def integer(value: Any) -> Literal:
    return Literal(value=value, type=INT64)


def boolean(value: Any) -> Literal:
    return Literal(value=value, type=BOOLEAN)


def null(type_: PWType = STRING) -> Literal:
    return Literal(value=None, type=type_)


def unique_name(node: Node, preferred: str) -> str:
    """A column name not already taken, for tools that add rather than replace."""
    schema = node.schema()
    if preferred not in schema:
        return preferred
    for suffix in range(2, 1000):
        candidate = f"{preferred}_{suffix}"
        if candidate not in schema:
            return candidate
    raise IRError(f"Could not find a free name based on {preferred!r}.")


def null_safe(guard: Expr, expression: Expr, *, type_: PWType = STRING) -> Expr:
    """Yield null wherever ``guard`` is null, and ``expression`` otherwise.

    Needed wherever an expression has a total answer: a `Case` with a default,
    a `coalesce` with a constant, a fallback for unparseable values. All of them
    happily produce that answer for a row that had no input at all, which turns
    "we do not know" into "we do know, and it is the default" -- the quietest
    way to corrupt a dataset.
    """
    return Case(
        branches=((Call(name="is_null", args=(guard,)), Literal(value=None, type=type_)),),
        default=expression,
    )


def all_null(*guards: Expr) -> Expr:
    """True when every one of these is null."""
    condition: Expr = Call(name="is_null", args=(guards[0],))
    for guard in guards[1:]:
        condition = Call(name="and", args=(condition, Call(name="is_null", args=(guard,))))
    return condition
