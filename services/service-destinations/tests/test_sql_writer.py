"""Delivering a dataset into PostgreSQL and MySQL tables (adoption-readiness A4, U3).

The planning tests always run. The delivery tests need real servers -- the
ones `docker-compose.connectors.yml` starts -- and skip with the reason when
CONNECTORS_TEST_POSTGRES_URL / CONNECTORS_TEST_MYSQL_URL are not set. A skip
is not a pass.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from service_destinations.sql_writer import plan_table, write_frame
from shared_python.errors import BadRequestError

FRAME = pd.DataFrame(
    {
        "Order ID": [1, 2, 3],
        "customer": ["ann", "bo", "cy"],
        "amount": [10.5, 20.0, None],
        "paid": [True, False, True],
        "placed at": pd.to_datetime(["2026-01-01T10:00:00Z", "2026-01-02T11:00:00Z", "2026-01-03T12:00:00Z"]),
    }
)


# ---------------------------------------------------------------- planning


def test_a_plan_names_columns_and_types_for_each_engine() -> None:
    postgres = plan_table(FRAME, destination_type="postgres", table="orders", schema=None, mode="replace", key_columns=None)
    mysql = plan_table(FRAME, destination_type="mysql", table="orders", schema=None, mode="update", key_columns=["customer"])
    assert [c.name for c in postgres.columns] == ["Order_ID", "customer", "amount", "paid", "placed_at"]
    assert {c.name: c.type_label for c in postgres.columns}["placed_at"] == "timestamp with time zone"
    assert {c.name: c.type_label for c in mysql.columns}["customer"] == "varchar(255)"
    assert mysql.key_columns == ("customer",)
    assert any("Renamed for the database" in note for note in postgres.notes)
    assert any("time zone" in note for note in mysql.notes)


def test_types_come_from_the_values_when_the_column_is_mixed_objects() -> None:
    """The platform's parser keeps each value's own type in an object column."""
    frame = pd.DataFrame(
        {"id": pd.Series([1, 2], dtype=object), "price": pd.Series([1, 2.5], dtype=object),
         "note": pd.Series([1, "n/a"], dtype=object), "empty": pd.Series([None, None], dtype=object)}
    )
    plan = plan_table(frame, destination_type="postgres", table="t", schema=None, mode="replace", key_columns=None)
    assert {c.name: c.type_label for c in plan.columns} == {
        "id": "bigint", "price": "double precision", "note": "text", "empty": "text",
    }


def test_updating_matching_rows_needs_a_key_that_exists() -> None:
    with pytest.raises(BadRequestError, match="key column"):
        plan_table(FRAME, destination_type="postgres", table="orders", schema=None, mode="update", key_columns=[])
    with pytest.raises(BadRequestError, match="not a column"):
        plan_table(FRAME, destination_type="postgres", table="orders", schema=None, mode="update", key_columns=["nope"])


@pytest.mark.parametrize("name", ["", "1orders", "orders;drop", "select", "x" * 70])
def test_a_bad_table_name_is_refused(name: str) -> None:
    with pytest.raises(BadRequestError):
        plan_table(FRAME, destination_type="postgres", table=name, schema=None, mode="replace", key_columns=None)


# ----------------------------------------------------------- real servers

SERVERS = {
    "postgres": os.environ.get("CONNECTORS_TEST_POSTGRES_URL"),
    "mysql": os.environ.get("CONNECTORS_TEST_MYSQL_URL"),
}


def _config(url: str) -> dict:
    parsed = make_url(url)
    return {
        "host": parsed.host, "port": parsed.port, "database": parsed.database,
        "username": parsed.username, "password": parsed.password, "ssl_mode": "disable",
    }


@pytest.fixture(params=["postgres", "mysql"])
def server(request):
    url = SERVERS[request.param]
    if not url:
        pytest.skip(f"Set CONNECTORS_TEST_{request.param.upper()}_URL to deliver into a real {request.param} server.")
    table = f"delivery_{uuid.uuid4().hex[:10]}"
    engine = create_engine(url)
    yield request.param, _config(url), table, engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    engine.dispose()


def _rows(engine, table: str) -> list[tuple]:
    quote = engine.dialect.identifier_preparer.quote
    sql = f"SELECT {quote('Order_ID')}, customer, amount FROM {table} ORDER BY {quote('Order_ID')}"
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def _deliver(server, frame: pd.DataFrame, mode: str, keys=None):
    kind, config, table, _engine = server
    plan = plan_table(frame, destination_type=kind, table=table, schema=None, mode=mode, key_columns=keys)
    return write_frame(frame, plan=plan, config=config)


def test_replace_writes_exactly_this_data(server) -> None:
    _deliver(server, FRAME, "replace")
    outcome = _deliver(server, FRAME.head(2), "replace")
    assert outcome.table_created
    assert _rows(server[3], server[2]) == [(1, "ann", 10.5), (2, "bo", 20.0)]


def test_append_adds_rows(server) -> None:
    _deliver(server, FRAME, "append")
    _deliver(server, FRAME, "append")
    assert len(_rows(server[3], server[2])) == 6


def test_updating_matching_rows_twice_leaves_no_duplicates(server) -> None:
    first = _deliver(server, FRAME, "update", keys=["Order ID"])
    changed = FRAME.copy()
    changed.loc[changed["Order ID"] == 2, "amount"] = 99.0
    extra = pd.DataFrame({"Order ID": [4], "customer": ["di"], "amount": [5.0], "paid": [False],
                          "placed at": [datetime(2026, 1, 4, tzinfo=UTC)]})
    second = _deliver(server, pd.concat([changed, extra], ignore_index=True), "update", keys=["Order ID"])

    assert first.table_created and first.rows_added == 3
    assert second.rows_updated == 3 and second.rows_added == 1
    rows = _rows(server[3], server[2])
    assert [row[0] for row in rows] == [1, 2, 3, 4]
    assert rows[1] == (2, "bo", 99.0)
    # The new table carries the key as its primary key, so the database itself refuses duplicates.
    assert inspect(server[3]).get_pk_constraint(server[2])["constrained_columns"] == ["Order_ID"]


def test_update_works_on_a_table_with_no_constraint(server) -> None:
    _deliver(server, FRAME, "append")  # created without a primary key
    outcome = _deliver(server, FRAME, "update", keys=["Order ID"])
    assert outcome.rows_updated == 3
    assert len(_rows(server[3], server[2])) == 3


def test_a_missing_column_is_explained(server) -> None:
    _deliver(server, FRAME[["Order ID", "customer"]], "replace")
    with pytest.raises(BadRequestError, match="has no column"):
        _deliver(server, FRAME, "append")
