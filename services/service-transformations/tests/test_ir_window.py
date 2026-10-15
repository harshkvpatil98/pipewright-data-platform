"""The `Window` node: what it means, what pushes down, and proof the two agree.

Every tree in the corpus runs twice, once in pandas and once as SQL against a
real database (SQLite always, PostgreSQL when `CONNECTORS_TEST_POSTGRES_URL`
names one, as CI does), and the answers must match value for value. The
corpus has ties, empty values, an empty partition key and mixed-case text on
purpose: they are where two engines quietly disagree.
"""

from __future__ import annotations

import os
import sqlite3
import uuid

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING

from service_transformations.ir.estimate import estimate
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import (
    Filter,
    IRError,
    Join,
    Node,
    Project,
    Scan,
    Sort,
    SortKey,
    Window,
    WindowCall,
    WindowFrame,
    pushable_to,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.planner import plan
from service_transformations.ir.rewrites import rewrite
from service_transformations.ir.sql_backend import Unsupported, to_sql

ORDERS = pd.DataFrame({
    "id": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "region": ["eu", "us", "eu", "us", "eu", None, "us", "eu", None],
    "amount": [10.0, 250.0, 300.0, None, 120.0, 75.5, 250.0, 10.0, 3.0],
    "label": ["a", "B", "c", "D", "e", "F", "g", "H", "b"],
    "qty": [7, 2, 3, 4, 5, 6, 7, 8, 9],
})
OTHER = pd.DataFrame({"region": ["eu", "apac", None], "manager": ["ana", "cal", "dee"]})

ORDERS_SCAN = Scan("orders", (("id", INT64), ("region", STRING), ("amount", FLOAT64), ("label", STRING),
                              ("qty", INT64)))
OTHER_SCAN = Scan("regions", (("region", STRING), ("manager", STRING)))
FRAMES = {"orders": ORDERS, "regions": OTHER}


def by(*columns: str, desc: bool = False, nulls_first: bool = False) -> tuple[SortKey, ...]:
    return tuple(SortKey(Column(c), "desc" if desc else "asc", nulls_first) for c in columns)


def window(*functions, within=("region",), order=by("amount")) -> Window:
    return Window(ORDERS_SCAN, within, order, tuple(functions))


WHOLE = WindowFrame(whole=True)

# (name, tree): every one of these pushes down, and must agree.
PUSHABLE: list[tuple[str, Node]] = [
    ("ranks_with_ties_and_a_null_key", window(
        ("rk", WindowCall("rank")), ("dr", WindowCall("dense_rank")),
        ("pr", WindowCall("percent_rank")), ("cd", WindowCall("cume_dist")))),
    ("ranks_descending_nulls_first", window(
        ("rk", WindowCall("rank")), ("dr", WindowCall("dense_rank")), order=by("amount", desc=True, nulls_first=True))),
    ("running_totals_with_ties_together", window(
        ("s", WindowCall("sum", (Column("amount"),))), ("a", WindowCall("avg", (Column("amount"),))),
        ("n", WindowCall("count", (Column("amount"),))), ("lo", WindowCall("min", (Column("amount"),))),
        ("hi", WindowCall("max", (Column("amount"),))))),
    ("whole_partition_totals", window(
        ("s", WindowCall("sum", (Column("amount"),), WHOLE)), ("n", WindowCall("count", (Column("amount"),), WHOLE)),
        ("lo", WindowCall("min", (Column("label"),), WHOLE)), ("q", WindowCall("sum", (Column("qty"),), WHOLE)))),
    ("no_partition", window(("rk", WindowCall("rank")), ("s", WindowCall("sum", (Column("qty"),))), within=())),
    ("ordered_by_mixed_case_text", window(("rk", WindowCall("rank")), within=(), order=by("label"))),
    ("ordered_by_two_keys", window(("rk", WindowCall("dense_rank")), within=(), order=by("region", "amount"))),
    ("integer_running_total", window(("s", WindowCall("sum", (Column("qty"),))), order=by("id"))),
    ("percent_of_total", Project(
        window(("t", WindowCall("sum", (Column("amount"),), WHOLE)), order=()),
        (("id", Column("id")), ("share", Call("div", (Column("amount"), Call("nullif", (Column("t"),
                                                                                     Literal(0, INT64))))))))),
    ("filter_on_a_window_value", Filter(window(("rk", WindowCall("rank"))), Call("le", (Column("rk"),
                                                                                       Literal(2, INT64))))),
    ("whole_number_division", Project(ORDERS_SCAN, (
        ("id", Column("id")), ("half", Call("div", (Column("qty"), Literal(2, INT64)))),
        ("by_zero", Call("div", (Column("qty"), Literal(0, INT64))))))),
    ("semi_join_never_repeats_and_skips_empty_keys", Join(
        ORDERS_SCAN, OTHER_SCAN, Call("eq", (Column("region"), Column("region"))), how="semi")),
    ("anti_join_keeps_empty_keys", Join(
        ORDERS_SCAN, OTHER_SCAN, Call("eq", (Column("region"), Column("region"))), how="anti")),
    ("sort_by_text_then_number", Sort(ORDERS_SCAN, by("label") + by("amount", desc=True, nulls_first=True))),
]

ORDERED = {"sort_by_text_then_number"}

#: These depend on the order of tied rows, so they stay here.
LOCAL: list[tuple[str, Node]] = [
    ("row_number", window(("rn", WindowCall("row_number")))),
    ("lag", window(("p", WindowCall("lag", (Column("amount"),))))),
    ("lead", window(("p", WindowCall("lead", (Column("amount"),))))),
    ("ntile", window(("t", WindowCall("ntile", (Literal(2, INT64),))))),
    ("first_value", window(("f", WindowCall("first_value", (Column("label"),), WHOLE)))),
    ("rows_frame", window(("s", WindowCall("sum", (Column("amount"),), WindowFrame("rows", 1))))),
    ("running_rows", window(("s", WindowCall("sum", (Column("amount"),), WindowFrame("rows"))))),
    ("product", window(("p", WindowCall("product", (Column("amount"),))))),
    ("ema", window(("e", WindowCall("ema", (Column("amount"), Literal(3, INT64)))))),
]


def _normalise(frame: pd.DataFrame, ordered: bool) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        series = frame[column].reset_index(drop=True)
        numeric = pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
        values = []
        for value in series:
            if value is None or pd.isna(value):
                values.append(None)
            elif numeric or isinstance(value, (int, float)):
                values.append(round(float(value), 9))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    if not ordered and len(out):
        out = out.sort_values(by=list(out.columns), na_position="last", key=lambda s: s.map(
            lambda v: (v is None, str(type(v)), v if v is not None else 0))).reset_index(drop=True)
    return out


def _agree(name: str, tree: Node, dialect: str, connection) -> None:
    sql: object = to_sql(tree, dialect)
    local = _normalise(execute(tree, FRAMES), name in ORDERED)
    if not isinstance(connection, sqlite3.Connection):
        from sqlalchemy import text

        sql = text(sql)
    remote = _normalise(pd.read_sql_query(sql, connection), name in ORDERED)
    assert list(local.columns) == list(remote.columns), f"{name}\n{sql}"
    pd.testing.assert_frame_equal(local, remote, check_dtype=False, obj=f"{name}\nSQL: {sql}")


@pytest.fixture(scope="module")
def sqlite_db():
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("orders", connection, index=False)
    OTHER.to_sql("regions", connection, index=False)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def postgres_db():
    url = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("CONNECTORS_TEST_POSTGRES_URL is not set")
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    schema = f"window_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    with engine.begin() as connection:
        connection.execute(text(f'SET search_path TO "{schema}"'))
        ORDERS.to_sql("orders", connection, index=False)
        OTHER.to_sql("regions", connection, index=False)
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    yield connection
    connection.close()
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.mark.parametrize(("name", "tree"), PUSHABLE, ids=[name for name, _ in PUSHABLE])
def test_sqlite_agrees(name: str, tree: Node, sqlite_db) -> None:
    _agree(name, tree, "sqlite", sqlite_db)


@pytest.mark.parametrize(("name", "tree"), PUSHABLE, ids=[name for name, _ in PUSHABLE])
def test_postgres_agrees(name: str, tree: Node, postgres_db) -> None:
    _agree(name, tree, "postgres", postgres_db)


@pytest.mark.parametrize(("name", "tree"), LOCAL, ids=[name for name, _ in LOCAL])
def test_an_order_among_ties_never_pushes_down(name: str, tree: Node) -> None:
    for dialect in ("postgres", "sqlite", "duckdb", "mysql"):
        assert not pushable_to(dialect, tree)
        with pytest.raises(Unsupported):
            to_sql(tree, dialect)
    assert len(execute(tree, FRAMES)) == len(ORDERS)


class TestWhatItMeans:
    def run(self, *functions, within=("region",), order=by("amount")) -> pd.DataFrame:
        return execute(window(*functions, within=within, order=order), FRAMES)

    def test_the_rows_keep_their_order(self) -> None:
        out = self.run(("rk", WindowCall("rank")))
        assert out["id"].tolist() == ORDERS["id"].tolist()

    def test_ties_share_a_rank_and_the_next_is_skipped(self) -> None:
        out = self.run(("rk", WindowCall("rank")), ("dr", WindowCall("dense_rank")), within=(), order=by("qty"))
        ranks = dict(zip(out["id"], zip(out["rk"], out["dr"])))
        assert ranks[2] == (1, 1) and ranks[3] == (2, 2)
        assert ranks[1] == ranks[7] == (6, 6) and ranks[8] == (8, 7)

    def test_an_empty_key_is_a_partition_of_its_own(self) -> None:
        out = self.run(("n", WindowCall("count", (Column("id"),), WHOLE)))
        assert out.loc[out["region"].isna(), "n"].tolist() == [2, 2]

    def test_empty_values_sort_last_unless_asked(self) -> None:
        last = self.run(("rk", WindowCall("rank")), within=("region",), order=by("amount"))
        first = self.run(("rk", WindowCall("rank")), within=("region",), order=by("amount", nulls_first=True))
        row = ORDERS.index[ORDERS["id"] == 4][0]
        assert last.loc[row, "rk"] == 3 and first.loc[row, "rk"] == 1

    def test_a_lag_default_fills_past_the_edge_not_an_empty_value(self) -> None:
        out = self.run(("p", WindowCall("lag", (Column("amount"), Literal(1, INT64), Literal(-1.0, FLOAT64)))),
                       order=by("id"))
        values = dict(zip(out["id"], out["p"]))
        assert values[2] == -1.0  # first in "us": past the edge
        assert pd.isna(values[7])  # the row before in "us" (id 4) is itself empty

    def test_a_running_total_skips_empty_values(self) -> None:
        out = self.run(("s", WindowCall("sum", (Column("amount"),), WindowFrame("rows"))), order=by("id"))
        values = dict(zip(out["id"], out["s"]))
        assert values[4] == 250.0 and values[7] == 500.0

    def test_a_total_of_nothing_is_empty_not_zero(self) -> None:
        frame = pd.DataFrame({"g": ["a", "a"], "v": [None, None]})
        scan = Scan("t", (("g", STRING), ("v", FLOAT64)))
        out = execute(Window(scan, ("g",), (), (("s", WindowCall("sum", (Column("v"),), WHOLE)),)), {"t": frame})
        assert out["s"].isna().all()

    def test_ties_together_give_tied_rows_the_same_running_total(self) -> None:
        out = self.run(("s", WindowCall("sum", (Column("qty"),))), within=(), order=by("amount"))
        totals = dict(zip(out["id"], out["s"]))
        # In order of amount: 3.0 (qty 9), then 10.0 twice (7 and 8) together.
        assert totals[9] == 9 and totals[1] == totals[8] == 24
        assert totals[2] == totals[7] == 44

    def test_ntile_shares_rows_as_evenly_as_it_can(self) -> None:
        frame = pd.DataFrame({"v": list(range(10))})
        scan = Scan("t", (("v", INT64),))
        out = execute(Window(scan, (), by("v"), (("t", WindowCall("ntile", (Literal(3, INT64),))),)), {"t": frame})
        assert out["t"].tolist() == [1, 1, 1, 1, 2, 2, 2, 3, 3, 3]

    def test_an_empty_frame_gives_an_empty_frame_with_the_new_column(self) -> None:
        out = execute(window(("rk", WindowCall("rank"))), {"orders": ORDERS.iloc[0:0], "regions": OTHER})
        assert len(out) == 0 and "rk" in out.columns

    def test_a_new_column_cannot_take_an_existing_name(self) -> None:
        with pytest.raises(IRError, match="already exists"):
            window(("amount", WindowCall("rank")))

    def test_a_rank_needs_an_order(self) -> None:
        with pytest.raises(IRError, match="needs the rows in an order"):
            window(("rk", WindowCall("rank")), order=())

    def test_settings_must_be_constants(self) -> None:
        with pytest.raises(IRError, match="constants"):
            WindowCall("lag", (Column("amount"), Column("qty")))


class TestTheOptimiser:
    def test_a_filter_on_the_partition_columns_runs_first(self) -> None:
        tree = Filter(window(("rk", WindowCall("rank"))), Call("eq", (Column("region"), Literal("eu", STRING))))
        rewritten, applied = rewrite(tree)
        assert any(r.rule == "filter below window" for r in applied)
        assert _normalise(execute(rewritten, FRAMES), False).equals(_normalise(execute(tree, FRAMES), False))

    def test_a_filter_on_anything_else_stays_above(self) -> None:
        tree = Filter(window(("rk", WindowCall("rank"))), Call("gt", (Column("amount"), Literal(50.0, FLOAT64))))
        _, applied = rewrite(tree)
        assert not any(r.rule == "filter below window" for r in applied)

    def test_a_window_nobody_reads_is_dropped(self) -> None:
        tree = Project(window(("rk", WindowCall("rank"))), (("id", Column("id")),))
        rewritten, applied = rewrite(tree)
        assert not any(isinstance(part, Window) for part in rewritten.walk())
        assert any("not read above" in r.detail for r in applied)

    def test_pruning_keeps_what_the_window_reads(self) -> None:
        tree = Project(window(("s", WindowCall("sum", (Column("qty"),)))), (("s", Column("s")),))
        rewritten, _ = rewrite(tree)
        assert execute(rewritten, FRAMES)["s"].tolist() == execute(tree, FRAMES)["s"].tolist()

    def test_the_estimate_keeps_the_row_count(self) -> None:
        from shared_python.statistics import TableStats

        stats = {"orders": TableStats(rows=1000, columns={}, method="test")}
        assert estimate(window(("rk", WindowCall("rank"))), stats).rows == 1000

    def test_postgres_runs_it_and_mysql_does_not(self) -> None:
        tree = window(("rk", WindowCall("rank")))
        assert plan(tree, "postgresql").local_count == 0
        mysql = plan(tree, "mysql")
        assert mysql.local_count == 1
        assert any("window" in decision.reason for decision in mysql.decisions if not decision.pushed)

    def test_a_tie_order_keeps_the_window_here_and_says_why(self) -> None:
        tree = window(("rn", WindowCall("row_number")))
        decided = plan(tree, "postgresql")
        assert decided.local_count == 1
        assert any("tied rows" in decision.reason for decision in decided.decisions if not decision.pushed)


class TestPostgresOrdersTextByCharacterCodes:
    def test_the_sql_says_so(self) -> None:
        sql = to_sql(Sort(ORDERS_SCAN, by("label")), "postgres")
        assert 'COLLATE "C"' in sql
        assert 'COLLATE "C"' not in to_sql(Sort(ORDERS_SCAN, by("amount")), "postgres")
