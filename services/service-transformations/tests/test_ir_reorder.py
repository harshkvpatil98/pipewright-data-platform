"""Join order by cost: the same rows, less in between (D2, O3).

Random runs of three and four inner joins are built over tables of very
different sizes, reordered from their statistics, and run as written and as
reordered on pandas and on SQLite: every pair must give the same rows. One
case is checked for the work it saves.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from service_ingestion.profiling import build_profile
from service_transformations.ir.estimate import estimate
from service_transformations.ir.expressions import Call, Column
from service_transformations.ir.nodes import Join, Scan
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.reorder import reorder_joins
from service_transformations.ir.sql_backend import to_sql
from shared_python.statistics import from_profile
from shared_python.types import INT64

RNG = np.random.default_rng(31)
SIZES = {"a": 4_000, "b": 40, "c": 600, "d": 9}
FRAMES = {
    name: pd.DataFrame({f"{name}_id": np.arange(rows), f"{name}_k": RNG.integers(0, 50, rows),
                        f"{name}_v": RNG.integers(0, 1_000, rows)})
    for name, rows in SIZES.items()
}
STATS = {name: from_profile(build_profile(dataframe=frame, sample_limit=3, file_size_bytes=0))
         for name, frame in FRAMES.items()}


def _scan(name: str) -> Scan:
    return Scan(name, tuple((column, INT64) for column in FRAMES[name].columns))


def _rows(frame: pd.DataFrame) -> list[tuple]:
    return sorted(map(tuple, frame[sorted(frame.columns)].astype("int64").to_numpy().tolist()))


def _random_tree(seed: int) -> Join:
    rng = np.random.default_rng(seed)
    names = list(rng.permutation(list(SIZES)))[: rng.integers(3, 5)]
    tree = _scan(names[0])
    for index, name in enumerate(names[1:], start=1):
        other = names[rng.integers(0, index)]
        column = "k" if rng.random() < 0.7 else "id"
        tree = Join(tree, _scan(name), on=Call("eq", (Column(f"{other}_{column}"), Column(f"{name}_{column}"))))
    return tree


@pytest.mark.parametrize("seed", range(40))
def test_any_order_chosen_gives_the_rows_written(seed: int) -> None:
    written = _random_tree(seed)
    chosen, _applied = reorder_joins(written, STATS)
    assert list(chosen.schema()) == list(written.schema())
    expected = _rows(execute(written, FRAMES))
    assert _rows(execute(chosen, FRAMES)) == expected
    with sqlite3.connect(":memory:") as db:
        for name, frame in FRAMES.items():
            frame.to_sql(name, db, index=False)
        assert _rows(pd.read_sql_query(to_sql(chosen, "sqlite"), db)) == expected


def test_the_order_chosen_keeps_less_in_between() -> None:
    # As written: the 4,000-row table with the 600-row one first, on a key that matches a lot.
    written = Join(
        Join(_scan("a"), _scan("c"), on=Call("eq", (Column("a_k"), Column("c_k")))),
        _scan("d"),
        on=Call("eq", (Column("c_id"), Column("d_id"))),
    )
    chosen, applied = reorder_joins(written, STATS)
    assert applied and applied[0].rule == "join order by cost"
    assert "then" in applied[0].detail
    assert _rows(execute(chosen, FRAMES)) == _rows(execute(written, FRAMES))
    between_written = len(execute(written.left, FRAMES))
    first_join = next(node for node in chosen.walk() if isinstance(node, Join) and not any(
        isinstance(child, Join) for child in (node.left, node.right)))
    between_chosen = len(execute(first_join, FRAMES))
    assert between_chosen < between_written / 10
    assert estimate(first_join, STATS).rows < estimate(written.left, STATS).rows


def test_what_it_cannot_reorder_it_leaves_as_written() -> None:
    two = Join(_scan("a"), _scan("b"), on=Call("eq", (Column("a_k"), Column("b_k"))))
    assert reorder_joins(two, STATS) == (two, [])
    left = Join(Join(_scan("a"), _scan("b"), on=Call("eq", (Column("a_k"), Column("b_k"))), how="left"),
                _scan("d"), on=Call("eq", (Column("a_id"), Column("d_id"))))
    assert reorder_joins(left, STATS)[1] == []


def test_the_random_cases_reorder_often_enough_to_prove_something() -> None:
    reordered = sum(1 for seed in range(40) if reorder_joins(_random_tree(seed), STATS)[1])
    assert reordered >= 10
