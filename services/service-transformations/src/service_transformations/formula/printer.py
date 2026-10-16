"""Write an IR expression as formula text: the parser, the other way (E2, X3).

The converters read another tool's expressions (Alteryx, Informatica, SSIS,
Talend, Power Query) into the IR and save them as formulas, so a converted
step reads like one written by hand and is edited the same way. What this
writes parses back to the same tree (``test_formula_printer.py`` proves it
over generated trees), so nothing changes on the way. An expression the
formula language cannot write is refused with the reason, never written as
something close.

Every operator is bracketed, so precedence never decides anything; a
condition with several outcomes is written as nested IFs, which the parser
reads back as the same nested cases (``if_chain`` builds them that way).
"""

from __future__ import annotations

import math
from decimal import Decimal

from shared_python.errors import BadRequestError

from service_transformations.ir.expressions import FUNCTIONS, Call, Case, Cast, Column, Expr, Literal

#: IR function -> the operator the parser reads into it.
OPERATORS = {
    "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%", "power": "^", "concat": "&",
    "eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
}


class Unwritable(BadRequestError):
    """An expression the formula language has no way to write."""


def to_formula(expr: Expr) -> str:
    """The formula that parses to ``expr``."""
    return _write(expr)


def if_chain(branches: list[tuple[Expr, Expr]], default: Expr | None) -> Expr:
    """CASE WHEN ... as the parser reads IF and IFS: one condition per IF when
    there is an otherwise, all of them in one IFS when there is not."""
    if not branches:
        if default is None:
            raise BadRequestError("A condition needs at least one outcome.")
        return default
    if default is None:
        return Case(tuple(branches))
    tree = default
    for condition, value in reversed(branches):
        tree = Case(((condition, value),), default=tree)
    return tree


def _write(expr: Expr) -> str:
    if isinstance(expr, Column):
        return _column(expr.name)
    if isinstance(expr, Literal):
        return _literal(expr)
    if isinstance(expr, Case):
        return _case(expr)
    if isinstance(expr, Cast):
        raise Unwritable("A change of type is written with a function here (TO_NUMBER, TO_TEXT, TO_DATE).")
    if isinstance(expr, Call):
        return _call(expr)
    raise Unwritable(f"{expr} cannot be written as a formula.")


def _column(name: str) -> str:
    if not name or name != name.strip() or "]" in name:
        raise Unwritable(f"The column {name!r} cannot be named in a formula: a name in [ ] cannot hold ] "
                         "or start or end with a space. Rename it first.")
    return f"[{name}]"


def _literal(literal: Literal) -> str:
    value = literal.value
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise Unwritable("A formula has no way to write a value that is not a number.")
        text = format(Decimal(repr(value)), "f")
        # A whole number with no point would read back as a whole-number value.
        return text if "." in text else f"{text}.0"
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    raise Unwritable(f"A formula has no way to write the value {value!r}.")


def _case(case: Case) -> str:
    if len(case.branches) == 1:
        (condition, value), = case.branches
        if case.default is None:
            return f"IF({_write(condition)}, {_write(value)})"
        return f"IF({_write(condition)}, {_write(value)}, {_write(case.default)})"
    if case.default is not None:
        # IFS has no otherwise, and nested IFs are a different tree; if_chain
        # builds the nested form, which is what the parser gives back.
        raise Unwritable("A condition with several outcomes and an otherwise is written as nested IFs.")
    parts = ", ".join(f"{_write(c)}, {_write(v)}" for c, v in case.branches)
    return f"IFS({parts})"


def _call(call: Call) -> str:
    if call.name in OPERATORS and len(call.args) == 2:
        left, right = call.args
        return f"({_write(left)} {OPERATORS[call.name]} {_write(right)})"
    if call.name == "neg" and len(call.args) == 1:
        return f"(-{_write(call.args[0])})"
    from service_transformations.formula.parser import _ALIASES

    signature = FUNCTIONS.get(call.name)
    # A name the parser reads as another function (MIN is LEAST there) would come back as that one.
    if signature is None or call.name in ("neg", "sub") or _ALIASES.get(call.name, call.name) != call.name:
        raise Unwritable(f"{call.name} cannot be written as a formula.")
    if signature.is_aggregate:
        raise Unwritable(f"{call.name.upper()} sums up many rows, which a formula on one row cannot.")
    return f"{call.name.upper()}({', '.join(_write(arg) for arg in call.args)})"
