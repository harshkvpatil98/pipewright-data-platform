"""A dbt project to recipes, checks and a workflow (E2, X3).

The fixture (`fixtures/conversions/dbt_shop`, written here from dbt's
published layout) is converted, every recipe is run here on its seeds, and
each model's rows are held to SQLite running the model's SQL. Its tests
become checks that pass on that data, and what has no exact conversion (a
macro, a snapshot, a division warehouses disagree on, a package's test) is
reported with the reason, never approximated.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from typing import Any

import pandas as pd
import pytest

from api_gateway.conversions.dbt import convert_dbt, read_zip, render
from api_gateway.conversions.model import Conversion, NotConverted
from service_ingestion.read_copy import parse as parse_file
from service_quality.engine import evaluate_rule
from service_transformations.executor import apply_transformation_steps
from service_transformations.parameters import resolve
from service_transformations.steps.context import StepContext
from shared_python.types import INT64, STRING

from conversion_harness import SEGMENTS, dbt_project_zip, dbt_sqlite_model, sorted_rows


def _lookup(need):
    return {"customer_id": INT64, "segment": STRING} if need.name == "crm_segments" else None


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_dbt(read_zip(dbt_project_zip()), _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    """Every recipe, run here in order, by key."""
    frames: dict[str, pd.DataFrame] = {f"seed:{s.name}": parse_file(s.data, file_type="csv", spec=None)
                                       for s in converted.seeds}
    frames["source:crm.segments"] = SEGMENTS
    ids: dict[str, str] = {}

    def resolved(value: Any) -> Any:
        if isinstance(value, dict) and "$dataset" in value:
            return ids.setdefault(value["$dataset"], str(uuid.uuid4()))
        if isinstance(value, dict):
            return {key: resolved(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolved(item) for item in value]
        return value

    for recipe in converted.recipes:
        steps = resolve(resolved(recipe.steps), recipe.parameters)
        by_id = {identifier: frames[key] for key, identifier in ids.items() if key in frames}
        context = StepContext(resolve_dataset=lambda identifier, by_id=by_id: by_id[identifier].copy(),
                              describe_dataset=lambda identifier: identifier)
        frames[recipe.key] = apply_transformation_steps(frames[recipe.reads].copy(), steps, context)[0]
    return frames


@pytest.mark.parametrize("model", ["stg_customers", "stg_orders", "stg_payments", "orders", "customers",
                                   "big_orders"])
def test_each_model_gives_what_the_warehouse_would(model: str, outputs) -> None:
    ours, theirs = outputs[f"model:{model}"], dbt_sqlite_model(model)
    assert list(ours.columns) == list(theirs.columns)
    assert sorted_rows(ours) == sorted_rows(theirs)
    assert len(ours) > 0


def test_the_report_says_what_converted_and_why_the_rest_did_not(converted: Conversion) -> None:
    entries = {e.subject: e for section in converted.sections for e in section.entries}
    for converted_subject in ("model stg_customers", "model customers", "model orders", "model big_orders",
                              "seed raw_orders", "test relationships on stg_orders.customer_id",
                              "test dbt_utils.accepted_range on customers.customer_lifetime_value",
                              "test assert_completed_orders_are_paid", "test not_null on crm.segments.customer_id"):
        assert entries[converted_subject].status == "converted", converted_subject
    refused = {
        "model average_order": "divides a whole number by a whole number",
        "model payments_in_dollars": "cents_to_dollars(), a macro",
        "macro cents_to_dollars": "never runs its code",
        "the table customers_snapshot": "keeps every version",
        "test dbt_utils.expression_is_true on orders.amount": "not a test this converts",
        "packages.yml": "from elsewhere",
    }
    for subject, reason in refused.items():
        assert entries[subject].status == "not converted" and reason in entries[subject].reason, subject
    # The incremental model says how it is built here.
    assert "full-refresh" in entries["model orders"].notes[0]
    # Step by step: what each part became.
    assert entries["model customers"].became[0].startswith("The recipe “customers”, step 1: Join, keeping every row")


def test_vars_become_parameters_and_the_sql_keeps_them(converted: Conversion) -> None:
    big = converted.recipe("model:big_orders")
    assert big.parameters == [{"name": "min_order_amount", "kind": "whole number", "default": 15,
                               "label": "Min order amount"}]
    assert "{{min_order_amount}}" in big.steps[-1]["config"]["sql"]


def test_every_check_passes_on_the_data_as_its_dbt_test_does(converted: Conversion, outputs) -> None:
    frames = {**outputs}
    assert {check.rule_type for check in converted.checks} == {"not_null", "unique", "allowed_values", "range",
                                                               "row_count"}
    for check in converted.checks:
        result = evaluate_rule(frames[check.reads], rule_type=check.rule_type, config=check.config)
        assert result.status == "passed", (check.name, result.message)
    # A test's recipe holds the failing rows: none here.
    assert len(outputs["test:1"]) == 0


def test_a_check_that_should_fail_does(converted: Conversion, outputs) -> None:
    orders = outputs["model:stg_orders"].copy()
    orders.loc[0, "status"] = "lost"
    check = next(c for c in converted.checks if c.key == "check:stg_orders.status.accepted_values")
    assert evaluate_rule(orders, rule_type=check.rule_type, config=check.config).status == "failed"


def test_the_workflow_builds_in_dbt_build_order(converted: Conversion) -> None:
    workflow = converted.workflows[0]
    keys = {task.config.get("pipeline_id", {}).get("$recipe"): task.node_key for task in workflow.tasks}
    edges = {(link.source, link.target) for link in workflow.links}
    gates = {task.config["dataset_id"]["$dataset"]: task.node_key for task in workflow.tasks
             if task.node_type == "quality_gate" and not task.config["dataset_id"]["$dataset"].startswith("test:")}
    # A model waits for the tests of the models it reads.
    assert (gates["model:stg_customers"], keys["model:customers"]) in edges
    assert (gates["source:crm.segments"], keys["model:customers"]) in edges
    assert (gates["model:orders"], keys["model:big_orders"]) in edges
    # A CTE's recipe runs before its model.
    assert (keys["model:customers·1"], keys["model:customers"]) in edges
    # A test runs once what it tests is built, not after that model's own tests.
    relationships = next(k for k in keys if k and k.startswith("test:") and "stg_orders" in
                         converted.recipe(k).name)
    assert (keys["model:stg_orders"], keys[relationships]) in edges
    assert (keys["model:stg_customers"], keys[relationships]) in edges


def test_jinja_is_read_never_run() -> None:
    for text, reason in [
        ("select {{ dbt_utils.star(ref('a')) }} from x", "a macro or code"),
        ("{% set cols = ['a'] %} select 1 as a", "{% set %}"),
        ("{% for c in cols %} {{ c }} {% endfor %}", "{% for %}"),
        ("select * from {{ this }}", "{{ this }}"),
        ("select {{ var('missing') }} as x", "has no value"),
        ("select * from {{ ref('pkg', 'model') }}", "package"),
        ("select {{ ref(model_name) }}", "worked out by code"),
    ]:
        with pytest.raises(NotConverted, match=re.escape(reason)):
            render(text, variables={}, what="The model m")
    rendered = render("select a from {{ ref('m') }} {% if not is_incremental() %} where a > 1 {% endif %}"
                      " {# a comment #}", variables={}, what="The model m")
    assert "where a > 1" in rendered.sql and "comment" not in rendered.sql and rendered.incremental


def test_a_zip_that_points_outside_itself_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.sql", "select 1")
    with pytest.raises(NotConverted, match="outside"):
        read_zip(buffer.getvalue())
