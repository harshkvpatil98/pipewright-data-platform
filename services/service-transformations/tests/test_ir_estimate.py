"""Row estimates from statistics, each with how it was got (D2, O2).

The estimator is checked against what the data actually does: statistics
are taken from real frames (through the same profile every dataset version
gets), each estimate is compared with the true row count, and a guess must
say it is one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from service_ingestion.profiling import build_profile
from shared_python.statistics import TableStats, from_profile
from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.estimate import UNKNOWN_ROWS, estimate
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import Aggregate, Filter, Join, Limit, Scan
from service_transformations.ir.pandas_backend import execute

RNG = np.random.default_rng(22)
N = 20_000
ORDERS = pd.DataFrame({
    "id": np.arange(N),
    "customer_id": RNG.integers(0, 2_000, N),
    "region": RNG.choice(["eu", "us", "apac", "latam"], N, p=[0.5, 0.3, 0.15, 0.05]),
    "amount": RNG.gamma(2.0, 50.0, N).round(2),
})
ORDERS.loc[RNG.choice(N, 1_000, replace=False), "amount"] = np.nan
CUSTOMERS = pd.DataFrame({"id": np.arange(2_000), "tier": RNG.integers(1, 4, 2_000)})
FRAMES = {"orders": ORDERS, "customers": CUSTOMERS}


def _stats(frame: pd.DataFrame) -> TableStats:
    return from_profile(build_profile(dataframe=frame, sample_limit=5, file_size_bytes=0))


STATS = {"orders": _stats(ORDERS), "customers": _stats(CUSTOMERS)}
ORD = Scan("orders", (("id", INT64), ("customer_id", INT64), ("region", STRING), ("amount", FLOAT64)))
C = Scan("customers", (("id", INT64), ("tier", INT64)))


def _close(tree, *, within: float) -> None:
    got = estimate(tree, STATS).rows
    actual = len(execute(tree, FRAMES))
    assert abs(got - actual) <= within * max(actual, 1), (str(tree), got, actual)


@pytest.mark.parametrize(("tree", "within"), [
    (Filter(ORD, Call("eq", (Column("region"), Literal("eu", STRING)))), 0.05),
    (Filter(ORD, Call("eq", (Column("region"), Literal("latam", STRING)))), 0.10),
    (Filter(ORD, Call("gt", (Column("amount"), Literal(150.0, FLOAT64)))), 0.10),
    (Filter(ORD, Call("le", (Column("amount"), Literal(40.0, FLOAT64)))), 0.10),
    (Filter(ORD, Call("is_null", (Column("amount"),))), 0.02),
    (Filter(ORD, Call("and", (Call("eq", (Column("region"), Literal("us", STRING))),
                            Call("gt", (Column("amount"), Literal(100.0, FLOAT64)))))), 0.15),
    (Filter(ORD, Call("in_list", (Column("region"), Literal("eu", STRING), Literal("us", STRING)))), 0.05),
    (Aggregate(ORD, (("region", Column("region")),), (("n", Call("count", (Column("id"),))),)), 0.0),
    (Join(ORD, C, Call("eq", (Column("customer_id"), Column("id")))), 0.05),
    (Limit(ORD, 10, 5), 0.0),
])
def test_estimates_are_close_to_what_happens(tree, within):
    _close(tree, within=within)


def test_every_estimate_says_how_and_a_guess_says_so():
    tree = Filter(Scan("nowhere", ORD.columns), Call("eq", (Column("region"), Literal("eu", STRING))))
    result = estimate(tree, STATS)
    assert result.steps[0].rows == UNKNOWN_ROWS and result.steps[0].guessed
    assert "no statistics" in result.steps[0].how
    assert result.guessed
    known = estimate(Filter(ORD, Call("eq", (Column("region"), Literal("eu", STRING)))), STATS)
    assert not known.guessed and "every row" in known.steps[0].how and "region = 'eu'" in known.steps[1].how


def test_widths_follow_the_types():
    assert estimate(ORD, STATS).width == 8 + 8 + 32 + 8
    assert estimate(ORD, STATS).bytes == N * 56


def test_the_studio_plan_sets_each_steps_estimate_beside_what_happened():
    """What the Studio shows: a recipe's steps, each with the rows expected after it."""
    from service_transformations.executor import apply_transformation_steps_with_outcomes
    from service_transformations.preview import _step_estimates
    from shared_python.types import UNKNOWN

    steps = [
        {"type": "filter_rows", "config": {"conditions": [{"column": "region", "operator": "equals", "value": "eu"}]}},
        {"type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 120}]}},
        {"type": "aggregate", "config": {"group_by": ["customer_id"], "aggregations": [
            {"column": "amount", "function": "sum", "output_column": "total"}]}},
    ]
    scan = Scan("orders", tuple((name, UNKNOWN) for name in ORDERS.columns))
    estimates = _step_estimates(scan, steps, STATS["orders"])
    _, _, outcomes = apply_transformation_steps_with_outcomes(
        ORDERS, [{"step_type": s["type"], "config": s["config"]} for s in steps])
    assert [e.index for e in estimates] == [0, 1, 2]
    for estimated, actual in zip(estimates[:2], outcomes[:2], strict=True):
        assert abs(estimated.rows - actual.rows_after) <= 0.12 * actual.rows_after, (estimated, actual)
    assert not estimates[0].guessed and "region" in estimates[0].how
    # Without statistics every estimate is a stated guess.
    assert all(e.guessed for e in _step_estimates(scan, steps, None))
