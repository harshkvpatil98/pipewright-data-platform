"""Joins: an empty key matches nothing, and the output is counted before it is built (D2).

pandas matches an empty key with another empty key; no SQL database does,
so the same join gave different rows in the IR's two backends. And a join
on a key repeated on both sides multiplies: it is counted exactly from the
key counts, before a row of it exists.
"""

from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd
import pytest

from shared_python.errors import BadRequestError
from shared_python.types import FLOAT64, STRING
from service_transformations.ir.expressions import Call, Column
from service_transformations.ir.nodes import Join, Scan
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import to_sql
from service_transformations.steps.join_size import check_join, join_output_rows

LEFT = pd.DataFrame({"k": [1.0, np.nan, 2.0, 1.0, np.nan], "a": ["x", "y", "z", "w", "v"]})
RIGHT = pd.DataFrame({"k2": [np.nan, 1.0, 3.0, 1.0, np.nan], "b": ["p", "q", "r", "s", "t"]})
L_SCAN = Scan("l", (("k", FLOAT64), ("a", STRING)))
R_SCAN = Scan("r", (("k2", FLOAT64), ("b", STRING)))


def _rows(frame: pd.DataFrame) -> list[tuple]:
    rows = [tuple(None if pd.isna(v) else v for v in row) for row in frame.itertuples(index=False)]
    return sorted(rows, key=lambda row: tuple((v is None, str(v)) for v in row))


def _join(how: str) -> Join:
    return Join(L_SCAN, R_SCAN, on=Call("eq", (Column("k"), Column("k2"))), how=how)


@pytest.mark.parametrize("how", ["inner", "left", "right"])
def test_an_empty_key_matches_nothing_on_both_backends(how: str) -> None:
    here = execute(_join(how), {"l": LEFT, "r": RIGHT})
    with sqlite3.connect(":memory:") as db:
        LEFT.to_sql("l", db, index=False)
        RIGHT.to_sql("r", db, index=False)
        there = pd.read_sql_query(to_sql(_join(how), "sqlite"), db)
    assert _rows(here) == _rows(there)
    assert len(here) == join_output_rows(LEFT, RIGHT, ["k"], ["k2"], how, nulls_match=False)


def test_joins_sqlite_cannot_write_keep_to_the_same_rule() -> None:
    """Full, semi and anti joins, against what SQL says they give."""
    frames = {"l": LEFT, "r": RIGHT}
    full = execute(_join("full"), frames)
    # Four matches on 1, then every row on either side that matched nothing, empty keys included.
    assert len(full) == 4 + 3 + 3 == join_output_rows(LEFT, RIGHT, ["k"], ["k2"], "outer", nulls_match=False)
    assert sorted(full["b"].dropna()) == ["p", "q", "q", "r", "s", "s", "t"]
    assert sorted(execute(_join("semi"), frames)["a"]) == ["w", "x"]
    assert sorted(execute(_join("anti"), frames)["a"]) == ["v", "y", "z"]


@pytest.mark.parametrize("how", ["inner", "left", "right", "outer"])
def test_the_count_is_exactly_what_pandas_makes(how: str) -> None:
    rng = np.random.default_rng(3)
    left = pd.DataFrame({"k": rng.integers(0, 40, 500), "j": rng.choice(["a", "b", None], 500)})
    right = pd.DataFrame({"key": rng.integers(20, 60, 300), "j": rng.choice(["a", "b", None], 300)})
    made = left.merge(right, how=how, left_on=["k", "j"], right_on=["key", "j"])
    assert join_output_rows(left, right, ["k", "j"], ["key", "j"], how) == len(made)


def test_a_join_that_would_multiply_past_the_limit_stops_before_it_is_built(monkeypatch) -> None:
    one_key = pd.DataFrame({"k": [7] * 30_000, "v": 1.0})
    with pytest.raises(BadRequestError, match="900,000,000 rows"):
        check_join(one_key, one_key, ["k"], ["k"], "inner")
    # Under the row cap, the memory ceiling still holds: 3,000 x 3,000 is 9,000,000 rows.
    monkeypatch.setenv("RUN_MEMORY_LIMIT_MB", "128")
    small = one_key.head(3_000)
    with pytest.raises(BadRequestError, match="RUN_MEMORY_LIMIT_MB"):
        check_join(small, small, ["k"], ["k"], "inner", max_rows=10_000_000)
    monkeypatch.setenv("RUN_MEMORY_LIMIT_MB", "4096")
    assert check_join(small, small, ["k"], ["k"], "inner", max_rows=10_000_000) == 9_000_000


@pytest.mark.skipif(not os.environ.get("CONNECTORS_TEST_POSTGRES_URL"),
                    reason="Set CONNECTORS_TEST_POSTGRES_URL to compare with PostgreSQL.")
@pytest.mark.parametrize("how", ["inner", "left", "right", "full"])
def test_an_empty_key_matches_nothing_on_postgresql_either(how: str) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["CONNECTORS_TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            LEFT.to_sql("l", conn, index=False, if_exists="replace")
            RIGHT.to_sql("r", conn, index=False, if_exists="replace")
            there = pd.read_sql_query(to_sql(_join(how), "postgres"), conn)
            conn.exec_driver_sql("DROP TABLE l; DROP TABLE r")
    finally:
        engine.dispose()
    assert _rows(execute(_join(how), {"l": LEFT, "r": RIGHT})) == _rows(there)
