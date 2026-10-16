"""Power Query M to recipes (E2, X3).

The fixture (`fixtures/conversions/power_query/sales.pq`, written here from
Microsoft's published M specification) is converted, and its recipes run
here on small tables. The rows are the ones M's rules give, worked out by
hand: two empty values are equal (so a join matches them), an empty value
sorts first, Table.Distinct keeps the first row. Number.Round breaks ties to
even, which no formula here does, so it is refused rather than rounded the
other way.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from api_gateway.conversions.model import Conversion, NotConverted
from api_gateway.conversions.power_query import MParser, Row, convert_power_query
from shared_python.types import FLOAT64, INT64, STRING

from conversion_harness import entries, rows, run_recipes

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "power_query" / "sales.pq"
CUSTOMERS = pd.DataFrame({"customer_id": [1, 2, 3], "name": ["Ann", "Bo", "Cy"], "tier": ["gold", "silver", None]})
ORDERS = pd.DataFrame({
    "order_id": [10, 11, 12, 13, 14, 15, 16],
    "customer_id": [1, 2, 3, 4, 1, 2, None],
    "amount": [120.0, 40.0, 75.5, 60.0, 0.0, 30.0, 99.0],
    "status": ["shipped", "shipped", "returned", "shipped", "shipped", "cancelled", "shipped"],
})
TYPES = {"customers": {"customer_id": INT64, "name": STRING, "tier": STRING},
         "orders": {"order_id": INT64, "customer_id": INT64, "amount": FLOAT64, "status": STRING}}


def _lookup(need):
    return TYPES.get(need.name.lower())


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_power_query({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    results = run_recipes(converted, {"source:customers": CUSTOMERS, "source:orders": ORDERS})
    return {recipe.name: results[recipe.key] for recipe in converted.recipes if recipe.complete}


def test_the_orders_query(outputs) -> None:
    orders = outputs["Orders"]
    assert list(orders.columns) == ["order_id", "customer_id", "amount", "status", "amount_with_tax",
                                    "customer_name", "tier", "band"]
    # Cancelled and nothing-to-pay orders are left out; sorted by amount, largest first.
    assert rows(orders) == [
        (10, 1, 120, "SHIPPED", 144, "Ann", "gold", "large"),
        (16, None, 99, "SHIPPED", 118.8, None, "none", "medium"),
        (12, 3, 75.5, "RETURNED", 90.6, "Cy", "none", "medium"),
        (13, 4, 60, "SHIPPED", 72, None, "none", "medium"),
        (11, 2, 40, "SHIPPED", 48, "Bo", "silver", "small"),
    ]


def test_a_group_and_a_rename(outputs) -> None:
    totals = outputs["Totals"]
    assert list(totals.columns) == ["customer_tier", "orders", "revenue", "largest"]
    assert sorted(rows(totals)) == [("gold", 1, 120, 120), ("none", 3, 234.5, 99), ("silver", 1, 40, 40)]


def test_what_did_not_convert_and_what_had_nothing_to_do(converted: Conversion) -> None:
    found = entries(converted)
    assert "Number.Round breaks a tie to even" in found["step Rounded Off"].reason
    assert found["the query Customers"].status == "nothing to do"
    assert [seed.name for seed in converted.seeds] == ["Targets (data)"]
    assert {recipe.name for recipe in converted.recipes} == {"Orders", "Totals"}
    assert {need.name for need in converted.needs} == {"customers", "Orders"}


def _each(text: str, columns: dict) -> object:
    from service_transformations.formula.printer import to_formula

    node = MParser(text).expression()
    return to_formula(Row(columns, "The step").body(node))


@pytest.mark.parametrize(("text", "formula"), [
    ('each [a] = null', "IS_NULL([a])"),
    ('each [a] <> "x"', 'NOT(COALESCE(([a] = "x"), FALSE))'),
    ('each [n] > 1 and not ([a] = "y")', 'AND(([n] > 1), NOT(COALESCE(([a] = "y"), FALSE)))'),
    ('each [a] & "!"', '([a] & "!")'),
    ('each [n] ?? 0', "COALESCE([n], 0)"),
    ('each Text.Middle([a], 1, 2)', "SUBSTRING([a], 2, 2)"),
    ('each Number.Round([n], 1, RoundingMode.AwayFromZero)', "ROUND([n], 1)"),
    ('(row) => row[n] * 2', "([n] * 2)"),
    ('each if [n] > 1 then "big" else "small"', 'IF(([n] > 1), "big", "small")'),
])
def test_each_expressions(text: str, formula: str) -> None:
    assert _each(text, {"a": STRING, "n": FLOAT64}) == formula


@pytest.mark.parametrize(("text", "reason"), [
    ("each Number.Round([n])", "tie to even"),
    ("each Text.From([n])", "region settings"),
    ("each [a] & [n]", "something other than text"),
    ("each List.Sum({1, 2})", "List.Sum is not an M function"),
    ("each _", "whole row"),
])
def test_what_has_no_exact_formula_is_refused(text: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason):
        _each(text, {"a": STRING, "n": FLOAT64})


def test_a_single_query_file_and_a_navigation_to_a_table() -> None:
    query = b'''let
        Source = Sql.Database("db.example.com", "shop"),
        dbo_Orders = Source{[Schema="dbo",Item="orders"]}[Data],
        Top = Table.FirstN(Table.Distinct(dbo_Orders, {"customer_id"}), 2)
    in
        Top'''
    converted = convert_power_query({"top.pq": query}, _lookup)
    recipe, = converted.recipes
    assert recipe.name == "top" and [s["step_type"] for s in recipe.steps] == ["remove_duplicates", "limit_rows"]
    assert run_recipes(converted, {"source:orders": ORDERS})["query:top"]["order_id"].tolist() == [10, 11]


def test_a_query_that_is_not_m_is_refused() -> None:
    with pytest.raises(NotConverted):
        convert_power_query({"x.pq": b"let x = in"}, _lookup)
