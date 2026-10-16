"""Formula text written from a tree reads back as the same tree (E2, X3).

The converters save other tools' expressions as formulas through
``to_formula``; if a printed formula parsed to anything else, a converted
step would compute something its source did not. Generated trees cover every
operator, nested conditions, quoting and the values a formula can hold.
"""

from __future__ import annotations

import random

import pytest

from service_transformations.formula.parser import parse_formula
from service_transformations.formula.printer import Unwritable, if_chain, to_formula
from service_transformations.ir.expressions import Call, Case, Cast, Column, Literal
from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING

COLUMNS = ["amount", "order date", "status", "a_b", "x1"]
OPERATORS = ["add", "sub", "mul", "div", "mod", "power", "concat", "eq", "ne", "lt", "le", "gt", "ge"]
FUNCTIONS = [("upper", 1), ("lower", 1), ("trim", 1), ("length", 1), ("abs", 1), ("round", 2), ("coalesce", 2),
             ("substring", 3), ("left", 2), ("right", 2), ("contains", 2), ("is_null", 1), ("is_not_null", 1),
             ("and", 2), ("or", 2), ("not", 1), ("in_list", 3), ("between", 3), ("concat", 3), ("replace", 3),
             ("to_number", 1), ("to_text", 1), ("year", 1), ("greatest", 2), ("least", 3)]


def _leaf(rng: random.Random):
    pick = rng.randrange(6)
    if pick == 0:
        return Column(rng.choice(COLUMNS))
    if pick == 1:
        return Literal(rng.randrange(0, 10_000), INT64)
    if pick == 2:
        return Literal(rng.choice([0.5, 12.25, 1e-07, 3.0, 1234567.125]), FLOAT64)
    if pick == 3:
        return Literal(rng.choice(["", "shipped", 'say "hi"', "it's", "a, b", "[x]"]), STRING)
    if pick == 4:
        return Literal(rng.choice([True, False]), BOOLEAN)
    return Literal(None, STRING)


def _tree(rng: random.Random, depth: int):
    if depth == 0 or rng.random() < 0.2:
        return _leaf(rng)
    pick = rng.randrange(5)
    if pick == 0:
        return Call(rng.choice(OPERATORS), (_tree(rng, depth - 1), _tree(rng, depth - 1)))
    if pick == 1:
        return Call("neg", (_tree(rng, depth - 1),))
    if pick == 2:
        name, arity = rng.choice(FUNCTIONS)
        return Call(name, tuple(_tree(rng, depth - 1) for _ in range(arity)))
    branches = [(_tree(rng, depth - 1), _tree(rng, depth - 1)) for _ in range(rng.randrange(1, 4))]
    return if_chain(branches, _tree(rng, depth - 1) if rng.random() < 0.6 else None)


@pytest.mark.parametrize("seed", range(400))
def test_a_generated_tree_reads_back_as_itself(seed: int) -> None:
    tree = _tree(random.Random(seed), 4)
    assert parse_formula(to_formula(tree)) == tree


def test_what_it_writes_reads_as_a_person_would_write_it() -> None:
    tree = if_chain([(Call("gt", (Column("amount"), Literal(100, INT64))), Literal("big", STRING))],
                    Literal("small", STRING))
    assert to_formula(tree) == 'IF(([amount] > 100), "big", "small")'
    assert to_formula(Call("concat", (Column("first name"), Literal(" ", STRING)))) == '([first name] & " ")'
    assert to_formula(Literal('say "hi"', STRING)) == '"say ""hi"""'
    assert to_formula(Literal(5.0, FLOAT64)) == "5.0"
    assert to_formula(Literal(1e-07, FLOAT64)) == "0.0000001"


def test_several_outcomes_with_an_otherwise_are_nested_ifs() -> None:
    a, b = Call("gt", (Column("x1"), Literal(1, INT64))), Call("gt", (Column("x1"), Literal(2, INT64)))
    tree = if_chain([(a, Literal("one", STRING)), (b, Literal("two", STRING))], Literal("none", STRING))
    assert to_formula(tree) == 'IF(([x1] > 1), "one", IF(([x1] > 2), "two", "none"))'
    with pytest.raises(Unwritable):
        to_formula(Case(((a, Literal(1, INT64)), (b, Literal(2, INT64))), default=Literal(3, INT64)))


@pytest.mark.parametrize("tree", [
    Column("a]b"), Column(" padded"), Cast(Column("amount"), INT64), Call("sum", (Column("amount"),)),
    Literal(float("nan"), FLOAT64), Call("min", (Column("amount"),)),
])
def test_what_a_formula_cannot_write_is_refused(tree) -> None:
    with pytest.raises(Unwritable):
        to_formula(tree)
