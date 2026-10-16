"""An Airflow DAG to a workflow, recipes and checks, read and never run (E2, X3).

The fixture (`fixtures/conversions/airflow/orders_daily.py`, written here
from Airflow's published DAG format) is converted; its SQL tasks become
recipes whose rows are held to SQLite running the same SQL, its check
operators become checks, and its dependencies, retries and schedule become
the workflow's. What runs code is reported, task by task, and never run.
"""

from __future__ import annotations

import re
import sqlite3
import textwrap
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from api_gateway.conversions.airflow import convert_airflow
from api_gateway.conversions.model import Conversion, NotConverted
from service_quality.engine import evaluate_rule
from service_transformations.executor import apply_transformation_steps
from service_transformations.parameters import resolve
from service_transformations.steps.context import StepContext
from shared_python.types import DATE, INT64, STRING

FIXTURE = Path(__file__).parent / "fixtures" / "conversions" / "airflow" / "orders_daily.py"
ORDERS = pd.DataFrame({
    "id": [1, 2, 3, 4, 5, 6],
    "customer_id": [10, 11, 10, 12, 13, 11],
    "status": ["paid", "test", "paid", "cancelled", "paid", "paid"],
    "amount": [1250, 990, 300, 4000, 15000, 875],
    "order_date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-02", "2026-01-03"],
})


def _lookup(need):
    if need.name == "orders":
        return {"id": INT64, "customer_id": INT64, "status": STRING, "amount": INT64, "order_date": DATE}
    return None


def _dag(body: str) -> Conversion:
    text = "from airflow import DAG\n" + textwrap.dedent(body)
    return convert_airflow({"dag.py": text.encode()}, _lookup)


@pytest.fixture(scope="module")
def converted() -> Conversion:
    return convert_airflow({FIXTURE.name: FIXTURE.read_bytes()}, _lookup)


@pytest.fixture(scope="module")
def outputs(converted: Conversion) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {"table:raw.orders": ORDERS}
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
        context = StepContext(resolve_dataset=lambda i, by_id=by_id: by_id[i].copy(), describe_dataset=str)
        frames[recipe.key] = apply_transformation_steps(frames[recipe.reads].copy(), steps, context)[0]
    return frames


def _sqlite(table: str) -> pd.DataFrame:
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("raw_orders", connection, index=False)
    text = FIXTURE.read_text()
    clean = re.search(r'CLEAN_ORDERS = """(.*?)"""', text, re.S).group(1)
    totals = re.search(r'CREATE OR REPLACE TABLE analytics.daily_totals AS(.*?)"""', text, re.S).group(1)
    clean = clean.replace("CREATE OR REPLACE TABLE analytics.clean_orders AS", "")
    clean = clean.replace("raw.orders", "raw_orders").replace("{{ params.min_amount }}", "0")
    connection.execute(f"CREATE VIEW clean_orders AS {clean}")
    connection.execute(f"CREATE VIEW daily_totals AS {totals.replace('analytics.clean_orders', 'clean_orders')}")
    return pd.read_sql(f"SELECT * FROM {table}", connection)


def _rows(frame: pd.DataFrame) -> list[tuple]:
    def value(v):
        if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
            return None
        return round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)

    return sorted((tuple(value(v) for v in row) for row in frame.itertuples(index=False)), key=repr)


@pytest.mark.parametrize(("key", "table"), [("task:build.clean_orders", "clean_orders"),
                                            ("task:build.daily_totals", "daily_totals")])
def test_each_sql_task_makes_what_the_warehouse_would(key: str, table: str, outputs) -> None:
    ours, theirs = outputs[key], _sqlite(table)
    assert list(ours.columns) == list(theirs.columns)
    assert _rows(ours) == _rows(theirs) and len(ours)


def test_its_checks_pass_as_airflow_s_do(converted: Conversion, outputs) -> None:
    assert {check.rule_type for check in converted.checks} == {"not_null", "unique", "range", "row_count"}
    for check in converted.checks:
        result = evaluate_rule(outputs[check.reads], rule_type=check.rule_type, config=check.config)
        assert result.status == "passed", (check.name, result.message)


def test_the_workflow_keeps_the_order_retries_and_parameters(converted: Conversion) -> None:
    workflow, = converted.workflows
    tasks = {task.node_key: task for task in workflow.tasks}
    assert set(tasks) == {"build_clean_orders", "build_daily_totals", "check_orders", "check_totals"}
    assert {(link.source, link.target) for link in workflow.links} == {
        ("build_clean_orders", "build_daily_totals"), ("build_daily_totals", "check_orders"),
        ("build_daily_totals", "check_totals")}
    # default_args give 2 retries 5 minutes apart; a task's own setting wins.
    assert (tasks["build_clean_orders"].retries, tasks["build_clean_orders"].retry_delay_seconds) == (2, 300)
    assert tasks["build_daily_totals"].retries == 4
    # {{ params.min_amount }} is the recipe's parameter, which the task passes from the run's.
    assert tasks["build_clean_orders"].config["parameters"] == {"min_amount": "{{ params.min_amount }}"}
    assert workflow.default_parameters == {"min_amount": 0}
    # Tasks did not convert, so it starts by hand, and the report gives its schedule.
    assert (workflow.trigger_type, workflow.cron_expression) == ("manual", None)
    overview = {e.subject: e for e in converted.sections[0].entries}
    assert "0 6 * * *, Europe/London" in overview["the workflow"].became[1]


def test_the_report_names_every_task_and_why(converted: Conversion) -> None:
    entries = {e.subject: e for section in converted.sections for e in section.entries}
    expected = {
        "task wait_for_export (FileSensor)": "waits for something outside",
        "task append_history (SQLExecuteQueryOperator)": "INSERT INTO",
        "task todays_orders (SQLExecuteQueryOperator)": "{{ ds }}",
        "task archive (BashOperator)": "runs a command",
        "task notify (PythonOperator)": "runs Python code",
        "task end (EmptyOperator)": "all_done",
        "distinct_check on analytics.clean_orders.status": "not a column check this converts",
        "no_negative_revenue on analytics.daily_totals": "row count",
    }
    for subject, reason in expected.items():
        assert entries[subject].status == "not converted" and reason in entries[subject].reason, subject
    assert entries["task start (EmptyOperator)"].status == "nothing to do"
    assert "waited for wait_for_export" in entries["task build.clean_orders (SQLExecuteQueryOperator)"].notes[0]


def test_a_complete_dag_keeps_its_schedule() -> None:
    converted = _dag('''
        import pendulum
        from airflow.operators.empty import EmptyOperator
        from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
        with DAG("nightly", schedule="@daily", start_date=pendulum.datetime(2026, 1, 1, tz="UTC")):
            a = SQLExecuteQueryOperator(task_id="a", sql="CREATE TABLE x AS SELECT id FROM raw.orders")
            b = SQLExecuteQueryOperator(task_id="b", sql="CREATE TABLE y AS SELECT id FROM x WHERE id > 1")
            a << EmptyOperator(task_id="first")
            a.set_downstream(b)
    ''')
    workflow, = converted.workflows
    assert (workflow.trigger_type, workflow.cron_expression, workflow.timezone) == ("cron", "0 0 * * *", "UTC")
    assert [(link.source, link.target) for link in workflow.links] == [("a", "b")]
    assert converted.recipe("task:b").reads == "task:a"


@pytest.mark.parametrize(("body", "subject", "reason"), [
    ('''
     from datetime import timedelta
     with DAG("d", schedule=timedelta(hours=2)):
         pass
     ''', "schedule", "timedelta"),
    ('''
     with DAG("d", schedule="@once"):
         pass
     ''', "schedule", "@once"),
    ('''
     from airflow.operators.empty import EmptyOperator
     with DAG("d"):
         for n in range(3):
             EmptyOperator(task_id=f"t{n}")
     ''', "line 5", "in a loop"),
    ('''
     from airflow.decorators import task
     with DAG("d"):
         @task
         def extract():
             return 1
     ''', "@task extract (line 6)", "Python"),
])
def test_what_is_code_is_reported_not_run(body: str, subject: str, reason: str) -> None:
    converted = _dag(body)
    entries = {e.subject: e for section in converted.sections for e in section.entries}
    assert entries[subject].status == "not converted" and reason in entries[subject].reason


def test_lists_chains_and_groups_link_as_airflow_does() -> None:
    converted = _dag('''
        from airflow.models.baseoperator import chain, cross_downstream
        from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator as Q
        from airflow.utils.task_group import TaskGroup
        with DAG("d"):
            a = Q(task_id="a", sql="CREATE TABLE ta AS SELECT id FROM raw.orders")
            with TaskGroup("g") as g:
                b = Q(task_id="b", sql="CREATE TABLE tb AS SELECT id FROM ta")
                c = Q(task_id="c", sql="CREATE TABLE tc AS SELECT id FROM tb")
                b >> c
            d = Q(task_id="d", sql="CREATE TABLE td AS SELECT id FROM tc")
            e = Q(task_id="e", sql="CREATE TABLE te AS SELECT id FROM ta")
            chain(a, g, [d, e])
            cross_downstream([d], [Q(task_id="f", sql="CREATE TABLE tf AS SELECT id FROM td")])
    ''')
    links = {(link.source, link.target) for link in converted.workflows[0].links}
    assert links == {("a", "g_b"), ("g_b", "g_c"), ("g_c", "d"), ("g_c", "e"), ("d", "f")}


def test_a_file_with_no_dag_is_refused() -> None:
    with pytest.raises(NotConverted, match="defines no workflow"):
        convert_airflow({"x.py": b"print('hello')"}, _lookup)
    with pytest.raises(NotConverted, match="not Python"):
        convert_airflow({"x.py": b"def ("}, _lookup)
