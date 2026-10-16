"""Build the daily order tables, check them, and tell the team."""

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models.baseoperator import chain
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.providers.common.sql.operators.sql import (
    SQLColumnCheckOperator,
    SQLExecuteQueryOperator,
    SQLTableCheckOperator,
)
from airflow.sensors.filesystem import FileSensor
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

CLEAN_ORDERS = """
CREATE OR REPLACE TABLE analytics.clean_orders AS
SELECT
    id AS order_id,
    customer_id,
    status,
    amount / 100.0 AS amount,
    order_date
FROM raw.orders
WHERE status <> 'test' AND amount >= {{ params.min_amount }}
"""


def tell_the_team(**context):
    print("Orders are built for", context["ds"])


with DAG(
    dag_id="orders_daily",
    description="Build the daily order tables, check them, and tell the team.",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/London"),
    catchup=False,
    default_args=default_args,
    params={"min_amount": 0},
    tags=["orders"],
) as dag:
    start = EmptyOperator(task_id="start")
    wait_for_export = FileSensor(task_id="wait_for_export", filepath="/exports/orders.csv")

    with TaskGroup("build") as build:
        clean_orders = SQLExecuteQueryOperator(task_id="clean_orders", conn_id="warehouse", sql=CLEAN_ORDERS)
        daily_totals = SQLExecuteQueryOperator(
            task_id="daily_totals",
            conn_id="warehouse",
            retries=4,
            sql="""
                CREATE OR REPLACE TABLE analytics.daily_totals AS
                SELECT order_date, COUNT(*) AS orders, SUM(amount) AS revenue
                FROM analytics.clean_orders
                WHERE status <> 'cancelled'
                GROUP BY order_date
            """,
        )
        clean_orders >> daily_totals

    check_orders = SQLColumnCheckOperator(
        task_id="check_orders",
        conn_id="warehouse",
        table="analytics.clean_orders",
        column_mapping={
            "order_id": {"null_check": {"equal_to": 0}, "unique_check": {"equal_to": 0}},
            "amount": {"min": {"geq_to": 0}, "max": {"leq_to": 10000}},
            "status": {"distinct_check": {"geq_to": 2}},
        },
    )
    check_totals = SQLTableCheckOperator(
        task_id="check_totals",
        conn_id="warehouse",
        table="analytics.daily_totals",
        checks={"has_rows": {"check_statement": "COUNT(*) >= 1"},
                "no_negative_revenue": {"check_statement": "MIN(revenue) >= 0"}},
    )
    append_history = SQLExecuteQueryOperator(
        task_id="append_history",
        conn_id="warehouse",
        sql="INSERT INTO analytics.order_history SELECT * FROM analytics.daily_totals",
    )
    todays_orders = SQLExecuteQueryOperator(
        task_id="todays_orders",
        conn_id="warehouse",
        sql="CREATE TABLE analytics.todays_orders AS SELECT * FROM analytics.clean_orders WHERE order_date = '{{ ds }}'",
    )
    archive = BashOperator(task_id="archive", bash_command="gzip /exports/orders.csv")
    notify = PythonOperator(task_id="notify", python_callable=tell_the_team)
    end = EmptyOperator(task_id="end", trigger_rule=TriggerRule.ALL_DONE)

    start >> wait_for_export >> build >> [check_orders, check_totals]
    check_totals >> append_history
    chain(check_orders, todays_orders, archive)
    notify.set_upstream(append_history)
    end.set_upstream([notify, archive])
