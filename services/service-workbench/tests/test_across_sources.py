"""One query across two databases and a dataset (D2, O4, O5).

Two SQLite files stand in for two connections and a frame for a dataset.
Every answer is checked against the same query run in one database holding
all three tables, so "across sources" can only differ from "in one place" in
how the work was split, never in the rows. The plans are checked too: what
each source ran, that filters and columns went into it, that a small side's
keys went to the other as IN lists, and that a wrong estimate was noticed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from service_ingestion.profiling import build_profile
from service_workbench import across
from shared_python.errors import BadRequestError
from shared_python.statistics import TableStats, from_profile
from shared_python.types import FLOAT64, INT64, STRING

RNG = np.random.default_rng(4)
ORDERS = pd.DataFrame({
    "id": np.arange(3_000),
    "customer_id": RNG.integers(0, 400, 3_000),
    "amount": RNG.gamma(2.0, 40.0, 3_000).round(2),
    "status": RNG.choice(["paid", "open", "refunded"], 3_000),
})
CUSTOMERS = pd.DataFrame({
    "id": np.arange(400),
    "name": [f"Customer {i}" for i in range(400)],
    "region_id": RNG.integers(0, 5, 400),
})
REGIONS = pd.DataFrame({"id": np.arange(5), "region": ["north", "south", "east", "west", "centre"]})
TYPES = {"int64": INT64, "float64": FLOAT64, "object": STRING}


def _stats(frame: pd.DataFrame) -> TableStats:
    return from_profile(build_profile(dataframe=frame, sample_limit=3, file_size_bytes=0))


class Files:
    """Two databases and a dataset."""

    def __init__(self, folder: Path, *, stats: dict[str, TableStats | None] | None = None) -> None:
        self.paths = {"shop": folder / "shop.db", "crm": folder / "crm.db"}
        with sqlite3.connect(self.paths["shop"]) as db:
            ORDERS.to_sql("orders", db, index=False)
        with sqlite3.connect(self.paths["crm"]) as db:
            CUSTOMERS.to_sql("customers", db, index=False)
        self.datasets = {"Regions": REGIONS}
        self.frames = {"shop.orders": ORDERS, "crm.customers": CUSTOMERS, "Regions": REGIONS}
        self.stats = stats or {}
        self.ran: list[str] = []

    def table(self, parts: list[str]) -> across.Table:
        if parts[0].lower() == "datasets" and len(parts) == 2:
            frame = self.datasets.get(parts[1])
            if frame is None:
                raise BadRequestError(f"No dataset is called {parts[1]!r}.")
            return across.Table(label=f'datasets."{parts[1]}"', kind="dataset", origin=f"dataset:{parts[1]}",
                                name=parts[1], schema=None, columns=self._columns(frame),
                                stats=self.stats.get(parts[1], _stats(frame)))
        if len(parts) not in (2, 3) or parts[0] not in self.paths:
            raise BadRequestError(f"No connection is called {parts[0]!r}.")
        name = parts[-1]
        key = f"{parts[0]}.{name}"
        if key not in self.frames:
            raise BadRequestError(f"{parts[0]} has no table {name!r}.")
        frame = self.frames[key]
        return across.Table(label=key, kind="connection", origin=f"connection:{parts[0]}", name=name,
                            schema=parts[1] if len(parts) == 3 else None, columns=self._columns(frame),
                            dialect="sqlite", stats=self.stats.get(key, _stats(frame)))

    @staticmethod
    def _columns(frame: pd.DataFrame):
        return [(str(name), TYPES[str(dtype)]) for name, dtype in frame.dtypes.items()]

    def fetch(self, origin: str, dialect: str, sql: str, max_rows: int) -> pd.DataFrame:
        self.ran.append(sql)
        with sqlite3.connect(self.paths[origin.split(":", 1)[1]]) as db:
            return pd.read_sql_query(sql, db).head(max_rows)

    def read_dataset(self, origin: str) -> pd.DataFrame:
        return self.datasets[origin.split(":", 1)[1]].copy()


@pytest.fixture()
def files(tmp_path: Path) -> Files:
    return Files(tmp_path)


@pytest.fixture()
def one_place() -> sqlite3.Connection:
    """All three tables in one database: what the answer must be."""
    db = sqlite3.connect(":memory:")
    ORDERS.to_sql("orders", db, index=False)
    CUSTOMERS.to_sql("customers", db, index=False)
    REGIONS.to_sql("regions", db, index=False)
    yield db
    db.close()


def _same(outcome: across.Outcome, db: sqlite3.Connection, sql: str, *, ordered: bool = False) -> None:
    expected = pd.read_sql_query(sql, db)
    got = pd.DataFrame(outcome.rows, columns=outcome.columns)
    assert list(got.columns) == list(expected.columns)
    assert outcome.row_count == len(expected)
    def as_rows(frame: pd.DataFrame) -> list[tuple]:
        return [tuple(None if pd.isna(v) else round(v, 6) if isinstance(v, float) else v for v in row)
                for row in frame.itertuples(index=False)]

    got_rows, expected_rows = as_rows(got), as_rows(expected)
    if not ordered:
        got_rows, expected_rows = sorted(got_rows, key=str), sorted(expected_rows, key=str)
    assert got_rows == expected_rows


def test_two_databases_and_a_dataset_give_what_one_database_gives(files: Files, one_place) -> None:
    outcome = across.run("""
        SELECT r.region, COUNT(*) AS orders, SUM(o.amount) AS sales
        FROM shop.main.orders o
        JOIN crm.customers c ON o.customer_id = c.id
        JOIN datasets."Regions" r ON c.region_id = r.id
        WHERE o.status = 'paid' AND o.amount > 20
        GROUP BY r.region
        ORDER BY sales DESC
    """, files)
    _same(outcome, one_place, """
        SELECT r.region, COUNT(*) AS orders, SUM(o.amount) AS sales
        FROM orders o JOIN customers c ON o.customer_id = c.id JOIN regions r ON c.region_id = r.id
        WHERE o.status = 'paid' AND o.amount > 20 GROUP BY r.region ORDER BY sales DESC
    """, ordered=True)
    sources = {source.source: source for source in outcome.sources}
    # The filter and the columns went into the orders database; it sent only what was needed.
    orders_sql = sources["shop.orders"].ran
    assert "WHERE" in orders_sql and "'paid'" in orders_sql and '"main"."orders"' in orders_sql
    assert '"id"' not in orders_sql.split("FROM")[1].split("WHERE")[0]  # only the columns used
    assert sources["shop.orders"].rows == int(((ORDERS.status == "paid") & (ORDERS.amount > 20)).sum())
    assert sources["shop.orders"].statistics == "every row"  # and says where its statistics came from
    assert outcome.rewrites and outcome.joins


def test_a_small_side_sends_its_keys_as_in_lists(files: Files, one_place) -> None:
    sql = """SELECT o.id, o.amount, c.name FROM crm.customers c JOIN shop.orders o ON o.customer_id = c.id
             WHERE c.name = 'Customer 7'"""
    outcome = across.run(sql, files)
    _same(outcome, one_place, sql.replace("crm.customers", "customers").replace("shop.orders", "orders"))
    orders = next(source for source in outcome.sources if source.source == "shop.orders")
    assert "IN (7)" in orders.ran and orders.method.startswith("only the 1 key")
    assert orders.rows == int((ORDERS.customer_id == 7).sum())


def test_many_keys_go_in_batches_of_a_thousand(files: Files, one_place, monkeypatch) -> None:
    monkeypatch.setattr(across, "IN_LIST_BATCH", 50)
    # 111 customers (1, 10 to 19, 100 to 199): a filter on the name cannot move to the orders side.
    sql = ("SELECT o.id, c.name FROM crm.customers c JOIN shop.orders o ON o.customer_id = c.id "
           "WHERE c.name LIKE 'Customer 1%'")
    outcome = across.run(sql, files)
    _same(outcome, one_place, sql.replace("crm.customers", "customers").replace("shop.orders", "orders"))
    orders = next(source for source in outcome.sources if source.source == "shop.orders")
    assert "3 batches" in orders.method and "-- and 2 more batches" in orders.ran


def test_keys_that_would_not_narrow_the_other_side_are_not_sent(files: Files, one_place) -> None:
    # c.id < 250 moves to the orders side as o.customer_id < 250 (equal columns), so every key
    # the customers send is already all the orders read: shipping them would save nothing.
    sql = "SELECT o.id, c.name FROM crm.customers c JOIN shop.orders o ON o.customer_id = c.id WHERE c.id < 250"
    outcome = across.run(sql, files)
    _same(outcome, one_place, sql.replace("crm.customers", "customers").replace("shop.orders", "orders"))
    orders = next(source for source in outcome.sources if source.source == "shop.orders")
    assert orders.method == "all of it" and "< 250" in orders.ran


def test_an_estimate_ten_times_out_changes_the_plan_and_says_so(tmp_path: Path, one_place) -> None:
    # The statistics say the customers are few; really they are all there, and match many orders.
    wrong = TableStats(rows=4, columns={}, method="out of date")
    files = Files(tmp_path, stats={"crm.customers": wrong})
    sql = "SELECT o.id, c.name FROM crm.customers c JOIN shop.orders o ON o.customer_id = c.id"
    outcome = across.run(sql, files)
    _same(outcome, one_place, sql.replace("crm.customers", "customers").replace("shop.orders", "orders"))
    assert any(note.startswith("switched") for note in outcome.notes)


def test_left_joins_cross_joins_distinct_case_and_like(files: Files, one_place) -> None:
    cases = [
        ("SELECT c.id, o.id AS order_id FROM crm.customers c LEFT JOIN shop.orders o ON o.customer_id = c.id "
         "WHERE c.id < 20", False),
        ("SELECT DISTINCT o.status FROM shop.orders o", False),
        ("SELECT r.region, CASE WHEN r.id > 2 THEN 'high' ELSE 'low' END AS band FROM datasets.\"Regions\" r "
         "WHERE r.region LIKE 's%' OR r.region LIKE '%st'", False),
        ("SELECT o.id FROM shop.orders o WHERE o.status IN ('open', 'refunded') AND o.amount BETWEEN 10 AND 20 "
         "ORDER BY o.id LIMIT 5 OFFSET 3", True),
        ("SELECT o.status, COUNT(DISTINCT o.customer_id) AS buyers FROM shop.orders o GROUP BY o.status "
         "HAVING COUNT(*) > 900", False),
        # An aggregate inside a function: the SUM is the aggregate, the ROUND works on its result.
        ("SELECT o.status, ROUND(SUM(o.amount) / COUNT(*), 2) AS mean FROM shop.orders o GROUP BY o.status", False),
    ]
    for sql, ordered in cases:
        outcome = across.run(sql, files)
        local = (sql.replace("crm.customers", "customers").replace("shop.orders", "orders")
                 .replace('datasets."Regions"', "regions"))
        local = local.replace("LIKE 's%'", "LIKE 's%'")
        _same(outcome, one_place, local, ordered=ordered)


def test_a_source_that_would_send_too_much_stops_the_query(files: Files, monkeypatch) -> None:
    monkeypatch.setattr(across, "MAX_SOURCE_ROWS", 1_000)
    with pytest.raises(BadRequestError, match="would send more than 1,000 rows"):
        across.run("SELECT o.id, c.name FROM shop.orders o JOIN crm.customers c ON o.customer_id = c.id", files)


@pytest.mark.parametrize(("sql", "says"), [
    ("SELECT * FROM orders", "No connection is called 'orders'"),
    ("SELECT id FROM shop.orders o JOIN crm.customers c ON o.customer_id = c.id", "more than one table"),
    ("SELECT o.nope FROM shop.orders o", "has no column 'nope'"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH"),
    ("UPDATE shop.orders SET amount = 0", "SELECT"),
    ("SELECT o.id FROM shop.orders o JOIN crm.customers c ON o.amount > c.id", "equal to another"),
    ("SELECT o.status, o.amount FROM shop.orders o GROUP BY o.status", "neither grouped by nor aggregated"),
    ("SELECT 1; SELECT 2", "one SELECT"),
])
def test_what_it_cannot_run_it_says_plainly(files: Files, sql: str, says: str) -> None:
    with pytest.raises(BadRequestError, match=says):
        across.run(sql, files)
