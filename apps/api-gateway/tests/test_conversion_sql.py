"""SQL to recipes gives what a SQL database gives (E2, X3).

Each query is turned into recipes (the main one and one for each CTE another
part reads as a table), the recipes are run here on the same rows, and the
answer is held to SQLite running the query itself. What the SQL step cannot
run, or what warehouses would read differently, is refused with the reason.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

import pandas as pd
import pytest

from api_gateway.conversions.model import NotConverted
from api_gateway.conversions.sql import Scope, compile_model, dataset_table, parse
from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext
from shared_python.types import FLOAT64, INT64, STRING

TABLES = {
    "customers": pd.DataFrame({"customer_id": [1, 2, 3, 4], "first_name": ["Ann", "Bo", "Cy", "Di"],
                               "region": ["north", "south", None, "north"]}),
    "orders": pd.DataFrame({"order_id": [10, 11, 12, 13, 14, 15], "customer_id": [1, 1, 2, None, 3, 9],
                            "status": ["shipped", "returned", "shipped", "shipped", "placed", "shipped"],
                            "order_date": ["2026-01-02", "2026-01-05", "2026-01-03", "2026-01-04", "2026-01-09",
                                           "2026-01-06"]}),
    "payments": pd.DataFrame({"payment_id": [100, 101, 102, 103, 104], "order_id": [10, 10, 11, 12, 99],
                              "amount": [12.5, 7.5, 20.0, 4.25, 3.0], "method": ["card", "gift", "card", "bank",
                                                                                 "card"]}),
}
TYPES = {"customer_id": INT64, "first_name": STRING, "region": STRING, "order_id": INT64, "status": STRING,
         "order_date": STRING, "payment_id": INT64, "amount": FLOAT64, "method": STRING}


def _scope() -> Scope:
    return Scope(tables={name: dataset_table(name, f"source:{name}", {c: TYPES[c] for c in frame.columns})
                         for name, frame in TABLES.items()})


def _run(sql: str) -> pd.DataFrame:
    """The query as recipes, run here."""
    chain, compiler = compile_model(parse(sql, "the query"), scope=_scope(), owner="model", owner_key="model",
                                    parameters={})
    frames: dict[str, pd.DataFrame] = {f"source:{name}": frame for name, frame in TABLES.items()}
    ids: dict[str, str] = {}

    def resolved(value: Any) -> Any:
        if isinstance(value, dict) and "$dataset" in value:
            return ids.setdefault(value["$dataset"], str(uuid.uuid4()))
        if isinstance(value, dict):
            return {key: resolved(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolved(item) for item in value]
        return value

    by_id = lambda: {identifier: frames[key] for key, identifier in ids.items()}  # noqa: E731

    def run(base: str, steps: list[dict]) -> pd.DataFrame:
        steps = resolved(steps)
        context = StepContext(resolve_dataset=lambda identifier: by_id()[identifier].copy(),
                              describe_dataset=lambda identifier: identifier)
        return apply_transformation_steps(frames[base].copy(), steps, context)[0]

    for helper in compiler.helpers:
        frames[helper.key] = run(helper.reads, helper.steps)
    return run(chain.base, chain.steps)


def _sqlite(sql: str) -> pd.DataFrame:
    connection = sqlite3.connect(":memory:")
    for name, frame in TABLES.items():
        frame.to_sql(name, connection, index=False)
    return pd.read_sql(sql, connection)


def _rows(frame: pd.DataFrame, ordered: bool) -> list[tuple]:
    def value(v):
        if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
            return None
        return round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)

    rows = [tuple(value(v) for v in row) for row in frame.itertuples(index=False)]
    return rows if ordered else sorted(rows, key=repr)


QUERIES = [
    # staging: rename and filter one table
    ("select order_id as id, customer_id, status from orders where status <> 'returned'", False),
    # import CTEs, a group, and a left join of two CTEs (jaffle-style)
    ("""with people as (select * from customers),
            placed as (select * from orders),
            customer_orders as (
                select customer_id, min(order_date) as first_order, max(order_date) as most_recent_order,
                       count(order_id) as number_of_orders
                from placed group by customer_id)
        select people.customer_id, people.first_name, customer_orders.first_order,
               customer_orders.number_of_orders
        from people left join customer_orders on people.customer_id = customer_orders.customer_id""", False),
    # a join of a CTE built on a join, then a group over it
    ("""with paid as (
            select orders.customer_id, payments.amount
            from payments left join orders on payments.order_id = orders.order_id)
        select customer_id, sum(amount) as total from paid group by customer_id""", False),
    # every kind of join, with clashing names on both sides
    ("select o.order_id, o.customer_id, c.customer_id as c_id, c.first_name from orders o "
     "join customers c on o.customer_id = c.customer_id", False),
    ("select o.order_id, c.customer_id, c.first_name from orders o "
     "left join customers c on o.customer_id = c.customer_id", False),
    ("select o.order_id, c.customer_id, c.first_name from orders o "
     "right join customers c on o.customer_id = c.customer_id", False),
    ("select o.order_id, c.customer_id, c.first_name from orders o "
     "full outer join customers c on o.customer_id = c.customer_id", False),
    # three tables, the third joined to the second
    ("select c.first_name, o.order_id, p.amount from customers c join orders o on o.customer_id = c.customer_id "
     "join payments p on p.order_id = o.order_id where p.amount > 5", False),
    # an inner join with more than equality in ON
    ("select o.order_id, p.amount from orders o join payments p on o.order_id = p.order_id and p.method = 'card'",
     False),
    # USING, and SELECT * with it
    ("select * from orders join payments using (order_id)", False),
    ("select order_id, amount from orders left join payments using (order_id)", False),
    # SELECT * across a join keeps both sides' columns
    ("select c.*, o.order_id from customers c join orders o on c.customer_id = o.customer_id", False),
    # window functions, ORDER BY a SELECT name, LIMIT
    ("select order_id, customer_id, row_number() over (partition by customer_id order by order_date) as n "
     "from orders order by order_id", True),
    ("select customer_id, count(*) as orders from orders where customer_id is not null group by customer_id "
     "having count(*) >= 1 order by orders desc, customer_id limit 2", True),
    # a subquery in FROM
    ("select s.status, s.n from (select status, count(*) as n from orders group by status) s where s.n > 1", False),
    # UNION ALL and UNION, with the second part's names differing
    ("select customer_id as id, first_name as label from customers union all "
     "select order_id, status from orders", False),
    ("select region from customers union select status from orders", False),
    ("select customer_id from customers intersect select customer_id from orders", False),
    ("select customer_id from customers except select customer_id from orders", False),
    # a cross join and a comma join
    ("select c.first_name, p.method from customers c cross join payments p where p.amount > 10", False),
    ("select c.first_name, o.order_id from customers c, orders o where c.customer_id = o.customer_id", False),
    # DISTINCT, CASE, COALESCE
    ("select distinct coalesce(region, 'none') as region, case when customer_id > 2 then 'late' else 'early' end "
     "as cohort from customers", False),
]


@pytest.mark.parametrize(("sql", "ordered"), QUERIES)
def test_the_recipes_give_what_sqlite_gives(sql: str, ordered: bool) -> None:
    if ("right join" in sql or "full outer" in sql) and sqlite3.sqlite_version_info < (3, 39):
        pytest.skip("SQLite before 3.39 has no RIGHT or FULL JOIN to compare with")
    ours, theirs = _run(sql), _sqlite(sql)
    assert [c.lower() for c in ours.columns] == [c.lower() for c in theirs.columns]
    assert _rows(ours, ordered) == _rows(theirs, ordered)


def test_a_cte_read_as_a_table_becomes_a_recipe_of_its_own() -> None:
    chain, compiler = compile_model(parse(QUERIES[1][0], "customers"), scope=_scope(), owner="customers",
                                    owner_key="model:customers", parameters={})
    assert [helper.name for helper in compiler.helpers] == ["customers · customer_orders"]
    # The import CTEs are the datasets themselves: no recipe of their own.
    assert chain.base == "source:customers"
    assert [step["config"].get("tool") for step in chain.steps] == ["join.sql", "code.sql"]


@pytest.mark.parametrize(("sql", "reason"), [
    ("select order_id / customer_id as ratio from orders", "whole number by a whole number"),
    ("select count(*) from orders", "no name"),
    ("select * from orders where customer_id in (select customer_id from customers)", r"IN \(SELECT"),
    ("select * from orders o left join payments p on o.order_id = p.order_id and p.amount > 1", "more than equal"),
    ("with recursive r as (select 1 as n) select * from r", "RECURSIVE"),
    ("select * from orders qualify row_number() over (order by order_id) = 1", "QUALIFY"),
    ("select o.order_id, c.customer_id from orders o join customers c on o.customer_id = c.customer_id "
     "join payments c2 on c2.order_id = o.order_id join refunds r on r.id = o.order_id", "refunds"),
    ("select * from orders o join customers c on o.customer_id = c.customer_id", "two columns called customer_id"),
    ("delete from orders", "not a SELECT"),
])
def test_what_it_cannot_convert_exactly_is_refused_with_the_reason(sql: str, reason: str) -> None:
    with pytest.raises(NotConverted, match=reason):
        compile_model(parse(sql, "the model"), scope=_scope(), owner="m", owner_key="m", parameters={})


def test_a_division_said_to_be_decimal_converts() -> None:
    assert _rows(_run("select order_id, order_id / 4.0 as quarter from orders"), False) == _rows(
        _sqlite("select order_id, order_id / 4.0 as quarter from orders"), False)
