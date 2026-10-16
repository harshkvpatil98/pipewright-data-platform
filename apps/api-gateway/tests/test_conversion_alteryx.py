"""An Alteryx workflow to recipes (E2, X3).

The fixture (`fixtures/conversions/alteryx/region_totals.yxmd`, written here
from Alteryx's published format) is converted and its recipes run here on a
small orders table. Each output's rows are the ones Alteryx's published
rules give, worked out by hand below: text plus an empty value is the text,
a comparison with an empty side is false, Join matches two empty keys, Sort
puts empty values last ascending. What has no exact conversion (Round, a
Python tool) stops its outputs, which become drafts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from api_gateway.conversions.alteryx import convert_alteryx, expression
from api_gateway.conversions.model import Conversion, NotConverted
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING

from conversion_harness import entries, rows, run_recipes

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "alteryx" / "region_totals.yxmd"
ORDERS = pd.DataFrame({
    "order_id": [1, 2, 3, 4, 5, 6, 7, 8],
    "customer": [" ann ", "bo", "cy", "ann", "di", "ed", "bo", "fay"],
    "region": ["North", "South", None, "North", "East", "West", "South", "North"],
    "amount": [120.5, 80.0, 45.0, 200.0, 0.0, 99.5, 150.0, None],
    "status": ["paid", "paid", "paid", "test", "paid", "paid", "refund", "paid"],
    "order_date": [date(2026, 1, d) for d in (2, 2, 3, 3, 4, 4, 5, 5)],
})
TYPES = {"order_id": INT64, "customer": STRING, "region": STRING, "amount": FLOAT64, "status": STRING,
         "order_date": DATE}


def _lookup(need):
    return TYPES if need.name == "orders" else None


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_alteryx({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    results = run_recipes(converted, {"file:orders": ORDERS})
    return {recipe.name: results[recipe.key] for recipe in converted.recipes if recipe.complete}


# The Formula's columns for orders 1, 2, 3, 6 and 7 (the Filter's T output).
FORMULA = {
    1: ("ANN", 144.6, "North/ANN", "large", 120.5, True),
    2: ("BO", 96.0, "South/BO", "small", 80, False),
    3: ("CY", 54.0, "/CY", "small", 0, False),
    6: ("ED", 119.4, "West/ED", "small", 99.5, False),
    7: ("BO", 180.0, "South/BO", "large", -150, False),
}


def _order(order_id: int) -> tuple:
    source = ORDERS.loc[ORDERS["order_id"] == order_id].iloc[0]
    customer, tax, label, size, net, named = FORMULA[order_id]
    return (order_id, customer, source["region"] if pd.notna(source["region"]) else None, source["amount"],
            source["status"], str(source["order_date"]), tax, label, size, net, named)


def test_the_filter_keeps_what_alteryx_keeps_and_its_f_output_the_rest(outputs) -> None:
    assert [row[0] for row in rows(outputs["excluded_orders"])] == [4, 5, 8]


def test_the_join_s_outputs(outputs) -> None:
    enriched = outputs["orders_enriched"]
    assert list(enriched.columns) == ["order_id", "customer", "region", "amount", "status", "order_date",
                                      "amount_with_tax", "label", "size", "net", "named_an", "region_manager"]
    assert rows(enriched) == [(*_order(1), "Nia"), (*_order(2), "Sol"), (*_order(7), "Sol")]
    # L: the orders with no region a manager has: an empty region, and West.
    assert rows(outputs["orders_without_region"]) == [_order(3), _order(6)]


def test_summarize_sort_and_record_id(outputs) -> None:
    totals = outputs["region_totals"]
    assert list(totals.columns) == ["place", "region", "total", "orders", "customers", "average"]
    assert rows(totals) == [(1, "North", 120.5, 1, 1, 120.5), (2, "South", -70, 2, 1, 115)]


def test_unique_and_sample(outputs) -> None:
    assert [row[:2] for row in rows(outputs["first_customers"])] == [(1, "ANN"), (2, "BO"), (3, "CY")]


def test_what_did_not_convert_stops_its_outputs_which_are_drafts(converted: Conversion) -> None:
    found = entries(converted)
    assert "Round() is not converted" in found["Formula (tool 18)"].reason
    assert found["JupyterCode (tool 17)"].status == "not converted"
    drafts = {recipe.name: recipe for recipe in converted.recipes if not recipe.complete}
    assert set(drafts) == {"rounded", "scored"}
    assert len(drafts["rounded"].steps) == 7 and "as far as it goes" in drafts["rounded"].description
    assert found["Browse (tool 16)"].status == "nothing to do"


def test_the_report_lists_every_output_step_by_step(converted: Conversion) -> None:
    became = entries(converted)["Output Data (tool 9)"].became
    assert became[0] == 'The recipe “region_totals”, step 1: Keep the rows where [status] != "test" AND [amount] > 0'
    assert any("Number the rows from 1 (place)" in line for line in became)


SCHEMA = {"a": STRING, "b": STRING, "n": FLOAT64, "m": FLOAT64, "flag": BOOLEAN}


@pytest.mark.parametrize(("text", "row", "expected"), [
    ('[a] + [b]', {"a": "x", "b": None}, "x"),
    ('[a] + [b]', {"a": None, "b": None}, None),
    ('[n] + [m]', {"n": 1.0, "m": None}, None),
    ('[a] = [b]', {"a": None, "b": None}, True),
    ('[a] = [b]', {"a": "x", "b": None}, False),
    ('[a] != [b]', {"a": "x", "b": None}, True),
    ('[n] < [m]', {"n": None, "m": 1.0}, False),
    ('[n] <= [m]', {"n": None, "m": None}, True),
    ('IsEmpty([a])', {"a": ""}, True),
    ('Contains([a], "AB")', {"a": "xaby"}, True),
    ('Contains([a], "AB", 0)', {"a": "xaby"}, False),
    ('Substring([a], 1, 2)', {"a": "hello"}, "el"),
    ('IF [n] > 1 THEN "big" ELSEIF [n] > 0 THEN "some" ELSE "none" ENDIF', {"n": 0.5}, "some"),
    ('[a] IN ("x", "y")', {"a": "y"}, True),
    ('[a] NOT IN ("x", "y")', {"a": None}, True),
])
def test_alteryx_s_null_rules(text: str, row: dict, expected) -> None:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.formula.printer import to_formula
    from service_transformations.ir.pandas_backend import evaluate

    tree = expression(text, SCHEMA, "The formula")
    frame = pd.DataFrame([{**{k: None for k in SCHEMA}, **row}])
    value = evaluate(parse_formula(to_formula(tree)), frame).iloc[0]
    assert (None if value is pd.NA or (isinstance(value, float) and pd.isna(value)) else value) == expected


@pytest.mark.parametrize(("text", "reason"), [
    ("Round([n], 1)", "Round() is not converted"),
    ("ToNumber([a])", "ToNumber() is not converted"),
    ("Regex_Match([a], 'x')", "Regex_Match(), which is not a Alteryx function"),
    ("Left([a], [n])", "worked out from the row"),
    ("[missing] + 1", "not a column here"),
])
def test_what_has_no_exact_formula_is_refused(text: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason.replace("(", r"\(").replace(")", r"\)")):
        expression(text, SCHEMA, "The formula")


def test_a_file_that_is_not_alteryx_is_refused() -> None:
    with pytest.raises(NotConverted, match="not an Alteryx workflow"):
        convert_alteryx({"x.yxmd": b"<Other />"}, _lookup)
    with pytest.raises(NotConverted, match="DOCTYPE"):
        convert_alteryx({"x.yxmd": b'<!DOCTYPE x [<!ENTITY a "b">]><AlteryxDocument />'}, _lookup)
