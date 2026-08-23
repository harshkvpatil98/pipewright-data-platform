"""Shorthand for declaring tools.

The catalogue modules are meant to read like a list of what the tools *are*,
not like a list of IR-building code. Everything mechanical lives here.
"""

from __future__ import annotations

from typing import Any, Callable

from service_transformations.ir.expressions import Expr
from service_transformations.tools import register
from service_transformations.tools.builders import call, column_tool
from service_transformations.tools.spec import (
    Accepts,
    Example,
    Param,
    ParamKind,
    ToolSpec,
)


def simple(
    name: str,
    title: str,
    category: str,
    summary: str,
    function: str,
    *,
    example: Example,
    synonyms: tuple[str, ...] = (),
    accepts: Accepts = Accepts.TEXTUAL,
    params: tuple[Param, ...] = (),
    extra_args: Callable[[dict[str, Any]], tuple[Expr, ...]] | None = None,
) -> ToolSpec:
    """A tool that is one IR function applied to one column.

    ``extra_args`` turns the tool's parameters into the function's trailing
    arguments, which is the only part that varies between the hundred or so
    tools with this shape.
    """

    def apply(column: Expr, resolved: dict[str, Any]) -> Expr:
        trailing = extra_args(resolved) if extra_args else ()
        return call(function, column, *trailing)

    return register(
        ToolSpec(
            name=name,
            title=title,
            category=category,
            summary=summary,
            build=column_tool(apply),
            example=example,
            params=params,
            synonyms=synonyms,
            accepts=accepts,
        )
    )


def custom(
    name: str,
    title: str,
    category: str,
    summary: str,
    apply: Callable[[Expr, dict[str, Any]], Expr],
    *,
    example: Example,
    synonyms: tuple[str, ...] = (),
    accepts: Accepts = Accepts.TEXTUAL,
    params: tuple[Param, ...] = (),
) -> ToolSpec:
    """A column tool whose expression is more than one function call."""
    return register(
        ToolSpec(
            name=name,
            title=title,
            category=category,
            summary=summary,
            build=column_tool(apply),
            example=example,
            params=params,
            synonyms=synonyms,
            accepts=accepts,
        )
    )


def frame(
    name: str,
    title: str,
    category: str,
    summary: str,
    build,
    *,
    example: Example,
    synonyms: tuple[str, ...] = (),
    params: tuple[Param, ...] = (),
    local_only: bool = False,
) -> ToolSpec:
    """A tool that reshapes the frame rather than one column."""
    return register(
        ToolSpec(
            name=name,
            title=title,
            category=category,
            summary=summary,
            build=build,
            example=example,
            params=params,
            synonyms=synonyms,
            accepts=Accepts.ANY,
            column_scoped=False,
            local_only=local_only,
        )
    )


TEXT_PARAM = Param
__all__ = ["Accepts", "Example", "Param", "ParamKind", "custom", "frame", "simple"]
