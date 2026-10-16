"""An Informatica PowerCenter mapping to recipes (E2, X3).

The fixture (`fixtures/conversions/informatica/m_orders.xml`, written here
from PowerCenter's published export format) is converted and its recipes
run here. Each target's rows are the ones PowerCenter's published rules
give, worked out by hand: || leaves out an empty side, the Joiner never
matches an empty key, the Sorter treats empty values as high, the Router's
default group takes what no group took. A Lookup, which this does not
convert, leaves its target a draft.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from api_gateway.conversions.informatica import convert_informatica, expression
from api_gateway.conversions.model import Conversion, NotConverted
from shared_python.types import FLOAT64, INT64, STRING

from conversion_harness import entries, rows, run_recipes

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "informatica" / "m_orders.xml"
ORDERS = pd.DataFrame({"order_id": [1, 2, 3, 4, 5, 6], "customer_id": [10, 11, 12, 99, 10, None],
                       "amount": [150.0, 80.0, 40.0, 120.0, 0.0, 60.0],
                       "status": ["paid", "paid", "test", "paid", "paid", "paid"],
                       "region": ["North", "South", "North", None, "East", "West"]})
CUSTOMERS = pd.DataFrame({"customer_id": [10, 11, 10], "name": ["Ann", "Bo", "Ann"]})


def _lookup(need):
    return {"orders": {"order_id": INT64, "customer_id": INT64, "amount": FLOAT64, "status": STRING,
                       "region": STRING},
            "customers": {"customer_id": INT64, "name": STRING}}.get(need.name.lower())


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_informatica({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    results = run_recipes(converted, {"source:orders": ORDERS, "source:customers": CUSTOMERS})
    return {recipe.name: results[recipe.key] for recipe in converted.recipes if recipe.complete}


def test_the_joined_and_sorted_target(outputs) -> None:
    out = outputs["ORDERS_OUT"]
    assert list(out.columns) == ["ORDER_ID", "CUSTOMER_NAME", "AMOUNT", "TAX", "LABEL", "SIZE_BAND", "TWICE"]
    assert rows(out) == [(1, "Ann", 150, 30, "North-paid", "large", 301),
                         (4, None, 120, 24, "-paid", "large", 241),
                         (2, "Bo", 80, 16, "South-paid", "small", 161),
                         (6, None, 60, 12, "West-paid", "small", 121)]


def test_the_aggregator(outputs) -> None:
    totals = outputs["REGION_TOTALS"]
    assert list(totals.columns) == ["REGION", "TOTAL", "ORDERS"]
    assert sorted(rows(totals), key=repr) == sorted([(None, 120, 1), ("North", 150, 1), ("South", 80, 1),
                                                     ("West", 60, 1)], key=repr)


def test_the_router_s_group_and_its_default(outputs) -> None:
    assert rows(outputs["BIG_ORDERS"]) == [(1, 150), (4, 120)]
    assert rows(outputs["OTHER_ORDERS"]) == [(2, 80), (6, 60)]


def test_what_did_not_convert(converted: Conversion) -> None:
    found = entries(converted)
    assert "Lookup Procedure is not a transformation this converts" in found["Lookup Procedure LKP_RATES"].reason
    draft = converted.recipe("informatica:m_orders:LOOKED_UP")
    assert draft is not None and not draft.complete
    assert found["session s_m_orders"].status == "not converted"
    assert found["Source Qualifier SQ_CUSTOMERS"].became == ["Reads its source's fields",
                                                             "Removes repeated rows (Select Distinct)"]


SCHEMA = {"A": STRING, "B": STRING, "N": FLOAT64}


@pytest.mark.parametrize(("text", "row", "expected"), [
    ("A || B", {"A": "x", "B": None}, "x"),
    ("A || B", {"A": None, "B": None}, None),
    ("CONCAT(A, B)", {"A": None, "B": "y"}, "y"),
    ("IIF(N > 1, 'big')", {"N": 0.5}, None),  # text with no third value is refused below; this is a number
    ("LTRIM(A)", {"A": "\t  x"}, "\t  x"),
    ("RTRIM(A)", {"A": "x  "}, "x"),
    ("SUBSTR(A, 0, 2)", {"A": "hello"}, "he"),
    ("DECODE(A, 'x', 'one', 'y', 'two', 'other')", {"A": "y"}, "two"),
    ("DECODE(A, 'x', 'one')", {"A": "z"}, None),
    ("UPPER(A) -- a comment", {"A": "a"}, "A"),
])
def test_powercenter_s_rules(text: str, row: dict, expected) -> None:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.formula.printer import to_formula
    from service_transformations.ir.pandas_backend import evaluate

    if text.startswith("IIF(N > 1, 'big')"):
        with pytest.raises(NotConverted, match="empty text"):
            expression(text, SCHEMA, "The port")
        assert to_formula(expression("IIF(N > 1, 5)", SCHEMA, "The port")) == "IF(([N] > 1), 5, 0)"
        return
    tree = expression(text, SCHEMA, "The port")
    frame = pd.DataFrame([{**{k: None for k in SCHEMA}, **row}])
    value = evaluate(parse_formula(to_formula(tree)), frame).iloc[0]
    assert (None if value is pd.NA or (isinstance(value, float) and pd.isna(value)) else value) == expected


@pytest.mark.parametrize(("text", "reason"), [
    ("ROUND(N)", "ROUND is not converted"),
    ("N % 2", "remainder"),
    ("$$START_DATE", "parameter"),
    (":LKP.LKP_RATES(A)", "lookup"),
    ("TO_CHAR(N)", "TO_CHAR is not converted"),
])
def test_what_has_no_exact_formula_is_refused(text: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason):
        expression(text, SCHEMA, "The port")


def test_an_export_that_is_not_powercenter_is_refused() -> None:
    with pytest.raises(NotConverted, match="not a PowerCenter export"):
        convert_informatica({"x.xml": b"<other/>"}, _lookup)
