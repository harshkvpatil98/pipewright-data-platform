"""The two IR backends must agree.

This is the test that makes pushdown trustworthy. Pushdown rewrites the user's
computation into SQL and runs it somewhere else; a query that returns *nearly*
the right answer is worse than one that refuses, because nobody notices.

So: every tree in the corpus is executed twice -- once by the pandas backend,
once as SQL against a real SQLite database over the same data -- and the two
frames must match value for value.

The same discipline found the real bugs in Phase 02 (predicted columns versus
what pandas actually produced) and is the reason that work holds up.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.expressions import Call, Case, Column, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import Unsupported, to_sql

ORDERS = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6, 7, 8],
        "region": ["eu", "us", "eu", "us", "eu", "apac", "us", "apac"],
        "amount": [10.0, 250.0, 300.0, 50.0, 120.0, 75.5, 250.0, 5.0],
        "label": ["a", "B", "c", "D", "e", "F", "g", "H"],
        "flag": [1, 0, 1, 0, 1, 1, 0, 1],
    }
)

REGIONS = pd.DataFrame(
    {
        "region": ["eu", "us", "nordics"],
        "manager": ["ana", "ben", "cal"],
    }
)

ORDERS_SCAN = Scan(
    "orders",
    (
        ("id", INT64),
        ("region", STRING),
        ("amount", FLOAT64),
        ("label", STRING),
        ("flag", INT64),
    ),
)
REGIONS_SCAN = Scan("regions", (("region", STRING), ("manager", STRING)))

FRAMES = {"orders": ORDERS, "regions": REGIONS}


@pytest.fixture(scope="module")
def sqlite_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("orders", connection, index=False)
    REGIONS.to_sql("regions", connection, index=False)
    yield connection
    connection.close()


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Compare values, not storage details.

    SQLite has type affinity rather than types, so an integer column can come
    back as int64 from one engine and object from the other while holding the
    same values. Dtype equality would fail on a difference nobody cares about.

    Every null becomes a real ``None``. Built element-wise rather than with
    ``.where(..., None)``, which quietly reintroduces ``np.nan`` on an object
    column -- and a comparison that passes only because two null flavours are
    conflated is not checking anything. pandas currently treats them as equal
    and warns that it will stop.
    """
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        series = frame[column].reset_index(drop=True)
        numeric = pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(
            series
        )
        values = []
        for value in series:
            if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                values.append(None)
            elif numeric:
                values.append(round(float(value), 9))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    return out


def _sorted_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Order-insensitive comparison, for trees with no ORDER BY of their own."""
    if frame.empty:
        return frame
    return frame.sort_values(by=list(frame.columns), na_position="last").reset_index(
        drop=True
    )


# Each case: (name, tree, whether the tree defines its own row order)
CASES: list[tuple[str, Node, bool]] = [
    ("scan", ORDERS_SCAN, False),
    (
        "project_rename_and_derive",
        Project(
            ORDERS_SCAN,
            (
                ("ident", Column("id")),
                ("double", Call("mul", (Column("amount"), Literal(2, INT64)))),
                ("shout", Call("upper", (Column("label"),))),
            ),
        ),
        False,
    ),
    (
        "filter_numeric",
        Filter(ORDERS_SCAN, Call("ge", (Column("amount"), Literal(100.0, FLOAT64)))),
        False,
    ),
    (
        "filter_conjunction",
        Filter(
            ORDERS_SCAN,
            Call(
                "and",
                (
                    Call("ge", (Column("amount"), Literal(50.0, FLOAT64))),
                    Call("eq", (Column("region"), Literal("eu", STRING))),
                ),
            ),
        ),
        False,
    ),
    (
        "filter_in_list",
        Filter(
            ORDERS_SCAN,
            Call(
                "in_list",
                (Column("region"), Literal("eu", STRING), Literal("apac", STRING)),
            ),
        ),
        False,
    ),
    (
        "filter_between",
        Filter(
            ORDERS_SCAN,
            Call(
                "between",
                (Column("amount"), Literal(50.0, FLOAT64), Literal(260.0, FLOAT64)),
            ),
        ),
        False,
    ),
    (
        "aggregate_grouped",
        Aggregate(
            ORDERS_SCAN,
            group_by=(("region", Column("region")),),
            aggregates=(
                ("total", Call("sum", (Column("amount"),))),
                ("n", Call("count", (Column("id"),))),
                ("biggest", Call("max", (Column("amount"),))),
                ("smallest", Call("min", (Column("amount"),))),
            ),
        ),
        False,
    ),
    (
        "aggregate_ungrouped",
        Aggregate(
            ORDERS_SCAN,
            aggregates=(
                ("total", Call("sum", (Column("amount"),))),
                ("n", Call("count", (Column("id"),))),
            ),
        ),
        False,
    ),
    (
        "aggregate_over_expression",
        Aggregate(
            ORDERS_SCAN,
            group_by=(("region", Column("region")),),
            aggregates=(
                (
                    "weighted",
                    Call("sum", (Call("mul", (Column("amount"), Column("flag"))),)),
                ),
            ),
        ),
        False,
    ),
    (
        "aggregate_distinct_count",
        Aggregate(
            ORDERS_SCAN,
            group_by=(("region", Column("region")),),
            aggregates=(("distinct_amounts", Call("count_distinct", (Column("amount"),))),),
        ),
        False,
    ),
    (
        "filter_then_aggregate_then_sort",
        Sort(
            Aggregate(
                Filter(ORDERS_SCAN, Call("ge", (Column("amount"), Literal(50.0, FLOAT64)))),
                group_by=(("region", Column("region")),),
                aggregates=(("total", Call("sum", (Column("amount"),))),),
            ),
            keys=(SortKey(Column("total"), "desc"),),
        ),
        True,
    ),
    (
        "sort_multi_key",
        Sort(
            ORDERS_SCAN,
            keys=(SortKey(Column("region"), "asc"), SortKey(Column("amount"), "desc")),
        ),
        True,
    ),
    ("limit", Limit(Sort(ORDERS_SCAN, keys=(SortKey(Column("id"), "asc"),)), count=3), True),
    (
        "limit_with_offset",
        Limit(Sort(ORDERS_SCAN, keys=(SortKey(Column("id"), "asc"),)), count=3, offset=2),
        True,
    ),
    ("distinct_all_columns", Distinct(Project(ORDERS_SCAN, (("region", Column("region")),))), False),
    (
        "inner_join",
        Join(
            ORDERS_SCAN,
            REGIONS_SCAN,
            on=Call("eq", (Column("region"), Column("region"))),
            how="inner",
        ),
        False,
    ),
    (
        "left_join_keeps_unmatched",
        Join(
            ORDERS_SCAN,
            REGIONS_SCAN,
            on=Call("eq", (Column("region"), Column("region"))),
            how="left",
        ),
        False,
    ),
    (
        "case_expression",
        Project(
            ORDERS_SCAN,
            (
                ("id", Column("id")),
                (
                    "band",
                    Case(
                        (
                            (
                                Call("ge", (Column("amount"), Literal(200.0, FLOAT64))),
                                Literal("large", STRING),
                            ),
                            (
                                Call("ge", (Column("amount"), Literal(50.0, FLOAT64))),
                                Literal("medium", STRING),
                            ),
                        ),
                        default=Literal("small", STRING),
                    ),
                ),
            ),
        ),
        False,
    ),
    (
        "text_functions",
        Project(
            ORDERS_SCAN,
            (
                ("up", Call("upper", (Column("label"),))),
                ("down", Call("lower", (Column("label"),))),
                ("size", Call("length", (Column("region"),))),
                ("joined", Call("concat", (Column("region"), Column("label")))),
            ),
        ),
        False,
    ),
    (
        "arithmetic",
        Project(
            ORDERS_SCAN,
            (
                ("plus", Call("add", (Column("amount"), Literal(1.5, FLOAT64)))),
                ("minus", Call("sub", (Column("amount"), Column("flag")))),
                ("times", Call("mul", (Column("amount"), Literal(3, INT64)))),
                ("absolute", Call("abs", (Call("neg", (Column("amount"),)),))),
            ),
        ),
        False,
    ),
    (
        "union_all",
        SetOp(
            Project(
                Filter(ORDERS_SCAN, Call("eq", (Column("region"), Literal("eu", STRING)))),
                (("region", Column("region")), ("amount", Column("amount"))),
            ),
            Project(
                Filter(ORDERS_SCAN, Call("eq", (Column("region"), Literal("us", STRING)))),
                (("region", Column("region")), ("amount", Column("amount"))),
            ),
            kind="union_all",
        ),
        False,
    ),
]


@pytest.mark.parametrize(("name", "tree", "ordered"), CASES, ids=[c[0] for c in CASES])
def test_pandas_and_sql_agree(
    name: str, tree: Node, ordered: bool, sqlite_db: sqlite3.Connection
) -> None:
    try:
        sql = to_sql(tree, "sqlite")
    except Unsupported as exc:  # pragma: no cover - keeps the corpus honest
        pytest.skip(f"sqlite cannot express this tree: {exc}")

    from_pandas = _normalise(execute(tree, FRAMES))
    from_sql = _normalise(pd.read_sql_query(sql, sqlite_db))

    assert list(from_pandas.columns) == list(from_sql.columns), (
        f"{name}: column names differ\n  pandas: {list(from_pandas.columns)}\n"
        f"  sql:    {list(from_sql.columns)}\n  {sql}"
    )

    if not ordered:
        from_pandas = _sorted_rows(from_pandas)
        from_sql = _sorted_rows(from_sql)

    pd.testing.assert_frame_equal(
        from_pandas,
        from_sql,
        check_dtype=False,
        check_like=False,
        obj=f"{name}\nSQL: {sql}",
    )


def test_the_corpus_is_actually_exercising_sql() -> None:
    """A corpus that silently skips everything would pass vacuously."""
    compiled = 0
    for _, tree, _ in CASES:
        try:
            to_sql(tree, "sqlite")
            compiled += 1
        except Unsupported:
            pass
    assert compiled >= len(CASES) - 2, f"only {compiled}/{len(CASES)} trees compiled"
