"""An SSIS package to recipes and a workflow (E2, X3).

The fixture (`fixtures/conversions/ssis/LoadOrders.dtsx`, written here from
Microsoft's published package format) is converted and its recipes run here.
Each destination's rows are the ones Microsoft's rules give, worked out by
hand: an operator with a NULL is NULL, so is ?: with a NULL condition, the
Conditional Split gives a row to its first condition that holds, Merge Join
with TreatNullsAsEqual off never matches an empty key, TRIM removes spaces.
The precedence constraints become the workflow's links.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from api_gateway.conversions.model import Conversion, NotConverted
from api_gateway.conversions.ssis import convert_ssis, expression
from shared_python.types import FLOAT64, INT64, STRING

from conversion_harness import entries, rows, run_recipes

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "ssis" / "LoadOrders.dtsx"
ORDERS = pd.DataFrame({"order_id": [1, 2, 3, 4, 5], "customer_id": [10, 11, 12, 99, None],
                       "amount": [150.0, 80.0, 0.0, 120.0, None],
                       "status": ["paid", "paid", "refunded", "open", "paid"],
                       "region": [" North ", "South", None, "North", "East"]})
CUSTOMERS = pd.DataFrame({"customer_id": [10, 11, 12], "name": ["Ann", "Bo", "Cy"], "active": [1, 0, 1]})


def _lookup(need):
    return {"orders": {"order_id": INT64, "customer_id": INT64, "amount": FLOAT64, "status": STRING,
                       "region": STRING},
            "customers": {"customer_id": INT64, "name": STRING, "active": INT64}}.get(need.name.lower())


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_ssis({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    results = run_recipes(converted, {"source:orders": ORDERS, "source:customers": CUSTOMERS})
    return {recipe.name: results[recipe.key] for recipe in converted.recipes if recipe.complete}


def test_the_split_gives_each_row_to_its_first_condition(outputs) -> None:
    assert rows(outputs["paid_orders"]) == [(1, 150, "large"), (4, 120, "large"), (2, 80, "small")]
    assert rows(outputs["other_orders"]) == [(3, 0, "REFUNDED"), (5, None, "PAID")]


def test_the_merge_join_never_matches_an_empty_key(outputs) -> None:
    joined = outputs["orders_with_customers"]
    assert list(joined.columns) == ["order_id", "customer_name", "amount", "region"]
    assert rows(joined) == [(5, None, None, "East"), (1, "Ann", 150, "North"), (2, None, 80, "South"),
                            (3, "Cy", 0, "none"), (4, None, 120, "North")]


def test_the_aggregate(outputs) -> None:
    assert sorted(rows(outputs["region_totals"]), key=repr) == sorted(
        [("North", 270, 2, 150), ("South", 80, 1, 80), ("none", 0, 1, 0), ("East", None, 1, None)], key=repr)


def test_the_workflow_follows_the_precedence_constraints(converted: Conversion) -> None:
    workflow, = converted.workflows
    task_of = {task.config["pipeline_id"]["$recipe"]: task.node_key for task in workflow.tasks}
    edges = {(link.source, link.target, link.condition) for link in workflow.links}
    archive = next(key for key in task_of if key.endswith("Archive file"))
    paid = next(key for key in task_of if key.endswith("Paid orders file"))
    branch = next(key for key in task_of if key.endswith("·1"))
    # A branch's recipe runs before the recipe that reads it; Archive after Load orders, whatever happened.
    assert (task_of[branch], task_of[paid], "on_success") in edges
    assert (task_of[paid], task_of[archive], "always") in edges
    found = entries(converted)
    assert "runs SQL" in found["task Clear staging"].reason
    assert "sends an email" in found["task Tell the team"].reason
    assert "did not convert" in found["the constraint from Archive to Tell the team"].reason


def test_a_lookup_leaves_its_destination_a_draft(converted: Conversion) -> None:
    draft = next(recipe for recipe in converted.recipes if recipe.name == "rated_orders")
    assert not draft.complete
    assert "cache" in entries(converted)["Lookup Look up rates"].reason


SCHEMA = {"a": STRING, "b": STRING, "n": FLOAT64, "w": INT64, "v": INT64}


@pytest.mark.parametrize(("text", "row", "expected"), [
    ('[a] + [b]', {"a": "x", "b": None}, None),
    ('[n] > 1 ? "big" : "small"', {"n": None}, None),
    ('[n] > 1 ? "big" : "small"', {"n": 0.5}, "small"),
    ('TRIM([a])', {"a": "\t x "}, "\t x"),
    ('REPLACENULL([a], "none")', {"a": None}, "none"),
    ('[w] / [v]', {"w": -7, "v": 2}, -3),
    ('SUBSTRING([a], 2, 3)', {"a": "hello"}, "ell"),
    ('(DT_WSTR, 10)[a]', {"a": "kept"}, "kept"),
    ('!ISNULL([a]) && [n] >= 1', {"a": "x", "n": 1.0}, True),
])
def test_microsoft_s_rules(text: str, row: dict, expected) -> None:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.formula.printer import to_formula
    from service_transformations.ir.pandas_backend import evaluate

    tree = expression(text, SCHEMA, "The expression")
    frame = pd.DataFrame([{**{k: None for k in SCHEMA}, **row}])
    value = evaluate(parse_formula(to_formula(tree)), frame).iloc[0]
    assert (None if value is pd.NA or (isinstance(value, float) and pd.isna(value)) else value) == expected


@pytest.mark.parametrize(("text", "reason"), [
    ("ROUND([n], 1)", "does not say how it rounds a half"),
    ("(DT_WSTR, 10)[n]", "changes"),
    ("(DT_I4)[n]", "whole number"),
    ("@[User::Since]", "variable"),
    ("[w] & 1", "bitwise"),
    ("GETDATE()", "clock"),
])
def test_what_has_no_exact_formula_is_refused(text: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason):
        expression(text, SCHEMA, "The expression")


def test_a_file_that_is_not_a_package_is_refused() -> None:
    with pytest.raises(NotConverted, match="not an SSIS package"):
        convert_ssis({"x.dtsx": b"<other/>"}, _lookup)
