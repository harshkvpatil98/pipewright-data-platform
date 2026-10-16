"""A Talend job to recipes and a workflow (E2, X3).

The fixture (`fixtures/conversions/talend/orders_job_0.1.item`, written here
from Talend's published job format) is converted and its recipes run here.
Each output's rows are what the job's Java gives, worked out by hand: a
unique-match lookup keeps the last row of a key, text + null is "null", a
whole number divided by a whole number is a whole number toward zero. The
OnSubjobOk trigger becomes a link of the workflow.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from api_gateway.conversions.model import Conversion, NotConverted
from api_gateway.conversions.talend import convert_talend, java
from shared_python.types import FLOAT64, INT64, STRING

from conversion_harness import entries, rows, run_recipes

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "talend" / "orders_job_0.1.item"
ORDERS = pd.DataFrame({"order_id": [1, 2, 3, 4, 5, 6], "customer_id": [10, 11, 12, 10, 13, None],
                       "amount": [150.0, 80.0, 40.0, 0.0, 60.0, 120.0],
                       "status": ["paid", "paid", "test", "paid", "refund", "paid"],
                       "region": ["North", "South", "North", "East", None, "West"]})
CUSTOMERS = pd.DataFrame({"customer_id": [10, 11, 10, 12], "name": ["Ann", "Bo", "Annabel", "Cy"]})


def _lookup(need):
    return {"orders": {"order_id": INT64, "customer_id": INT64, "amount": FLOAT64, "status": STRING,
                       "region": STRING},
            "customers": {"customer_id": INT64, "name": STRING}}.get(need.name.lower())


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_talend({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    results = run_recipes(converted, {"file:orders": ORDERS, "file:customers": CUSTOMERS})
    return {recipe.name: results[recipe.key] for recipe in converted.recipes if recipe.complete}


def test_the_tmap_output_sorted(outputs) -> None:
    enriched = outputs["enriched_orders"]
    assert list(enriched.columns) == ["order_id", "customer", "label", "amount_with_tax", "upper_status", "half"]
    # Customer 10's last row (Annabel) is its match; a null region is written "null".
    assert rows(enriched) == [(1, "Annabel", "North/paid", 180, "PAID", 0),
                              (6, None, "West/paid", 144, "PAID", 3),
                              (2, "Bo", "South/paid", 96, "PAID", 1),
                              (5, None, "null/refund", 72, "REFUND", 2)]


def test_a_second_tmap_output_with_its_own_filter(outputs) -> None:
    assert rows(outputs["big_orders"]) == [(1, 150), (6, 120)]


def test_filter_row_aggregate_row_and_uniq_row(outputs) -> None:
    assert sorted(rows(outputs["region_totals"])) == [("North", 150, 1), ("South", 80, 1), ("West", 120, 1)]
    assert rows(outputs["rejected_customers"]) == [(3, 12), (4, 10), (5, 13)]


def test_the_workflow_follows_the_trigger(converted: Conversion) -> None:
    workflow, = converted.workflows
    task_of = {task.config["pipeline_id"]["$recipe"]: task.node_key for task in workflow.tasks}
    edges = {(link.source, link.target, link.condition) for link in workflow.links}
    enriched = task_of["talend:orders_job:tFileOutputDelimited_1"]
    totals = task_of["talend:orders_job:tFileOutputDelimited_3"]
    lookup = task_of["talend:orders_job·1"]
    assert (lookup, enriched, "on_success") in edges  # the lookup's recipe before what reads it
    assert (enriched, totals, "on_success") in edges  # the second subjob after the first
    found = entries(converted)
    assert "runs Java code" in found["tJava tJava_1"].reason
    assert "links nothing" in found["SUBJOB_OK from tFileInputDelimited_3 to tJava_1"].reason


SCHEMA = {"a": STRING, "b": STRING, "n": FLOAT64, "w": INT64}
NAMES = {f"row1.{column}": column for column in SCHEMA}


@pytest.mark.parametrize(("text", "row", "expected"), [
    ('row1.a + row1.b', {"a": "x", "b": None}, "xnull"),
    ('row1.w / 2', {"w": -7}, -3),
    ('row1.a.trim().toUpperCase()', {"a": " x\t"}, "X"),
    ('row1.a.substring(1, 3)', {"a": "hello"}, "el"),
    ('"x".equals(row1.a)', {"a": None}, False),
    ('row1.a.equalsIgnoreCase("ABC")', {"a": "abc"}, True),
    ('row1.n > 1 ? "big" : "small"', {"n": 2.0}, "big"),
    ('row1.a == null', {"a": None}, True),
    ('StringHandling.UPCASE(row1.a)', {"a": "q"}, "Q"),
    ('(int) row1.n', {"n": -2.7}, -2),
])
def test_java_as_java_runs_it(text: str, row: dict, expected) -> None:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.formula.printer import to_formula
    from service_transformations.ir.pandas_backend import evaluate

    tree = java(text, SCHEMA, NAMES, "The expression")
    frame = pd.DataFrame([{**{k: None for k in SCHEMA}, **row}])
    value = evaluate(parse_formula(to_formula(tree)), frame).iloc[0]
    assert (None if value is pd.NA or (isinstance(value, float) and pd.isna(value)) else value) == expected


@pytest.mark.parametrize(("text", "reason"), [
    ("row1.a == row1.b", "compares which object"),
    ("Math.round(row1.n)", "half up"),
    ("row1.a + row1.n", "Java writes by its own rules"),
    ("context.dir", "context variable"),
    ("row1.a.matches(\"x\")", "not a Java method"),
    ("row1.w % 2", "is not converted"),
])
def test_what_has_no_exact_formula_is_refused(text: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason):
        java(text, SCHEMA, NAMES, "The expression")


def test_a_file_that_is_not_a_job_is_refused() -> None:
    with pytest.raises(NotConverted, match="not a Talend job"):
        convert_talend({"x.item": b"<other/>"}, _lookup)
