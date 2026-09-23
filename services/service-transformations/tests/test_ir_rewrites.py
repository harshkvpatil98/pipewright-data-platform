"""The rewrites must not change the answer, and must earn their keep.

Each rule in ``ir/rewrites.py`` is an algebraic identity. Saying so is not
evidence; this file is. Every tree in the corpus is executed four ways -- as
written and as rewritten, by pandas and by SQLite -- and all four must agree
value for value. A second set of tests shows the point of the exercise: a
plan that pushed nothing before now pushes the filter or the limit to the
source, and says which rewrite made that possible.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    Limit,
    Node,
    Project,
    Scan,
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute, register_extension
from service_transformations.ir.planner import plan
from service_transformations.ir.rewrites import rewrite
from service_transformations.ir.run_plan import execute_plan
from service_transformations.ir.sql_backend import Unsupported, to_sql

ORDERS = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6, 7, 8],
        "region": ["eu", "us", "eu", "apac", "us", "eu", None, "apac"],
        "amount": [10.0, 250.0, 300.0, 75.5, 50.0, 120.0, 40.0, None],
        "label": ["a", "B", "c", "D", "e", "F", "g", None],
    }
)
SCAN = Scan(
    "orders",
    (("id", INT64), ("region", STRING), ("amount", FLOAT64), ("label", STRING)),
)
FRAMES = {"orders": ORDERS}


@pytest.fixture(scope="module")
def db():
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("orders", connection, index=False)
    yield connection
    connection.close()


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        values = []
        for value in frame[column].reset_index(drop=True):
            if value is None or (
                not isinstance(value, (list, dict)) and pd.isna(value)
            ):
                values.append(None)
            elif pd.api.types.is_numeric_dtype(frame[column]):
                values.append(round(float(value), 9))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    return out


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.sort_values(by=list(frame.columns), na_position="last").reset_index(
        drop=True
    )


AMOUNT_GT_40 = Call("gt", (Column("amount"), Literal(40.0, FLOAT64)))
REGION_EU = Call("eq", (Column("region"), Literal("eu", STRING)))
BY_ID = (SortKey(Column("id")),)
PASS_THROUGH_WITH_DERIVED = (
    ("id", Column("id")),
    ("region", Column("region")),
    ("amount", Column("amount")),
    ("doubled", Call("mul", (Column("amount"), Literal(2.0, FLOAT64)))),
)
RENAMED = (
    ("id", Column("id")),
    ("rgn", Column("region")),
    ("amount", Column("amount")),
)

# (name, tree, ordered, expected rule names in order -- empty means "nothing applies")
CASES: list[tuple[str, Node, bool, list[str]]] = [
    (
        "filter below projection (pass-through columns)",
        Filter(Project(SCAN, PASS_THROUGH_WITH_DERIVED), AMOUNT_GT_40),
        False,
        ["filter below projection"],
    ),
    (
        "filter stays above a projection that renames what it reads",
        Filter(
            Project(SCAN, RENAMED), Call("eq", (Column("rgn"), Literal("eu", STRING)))
        ),
        False,
        [],
    ),
    (
        "filter stays above a projection that derives what it reads",
        Filter(
            Project(SCAN, PASS_THROUGH_WITH_DERIVED),
            Call("gt", (Column("doubled"), Literal(100.0, FLOAT64))),
        ),
        False,
        [],
    ),
    (
        "filter below sort",
        Filter(Sort(SCAN, BY_ID), REGION_EU),
        True,
        ["filter below sort"],
    ),
    (
        "two filters merge, three-valued logic intact (null region, null amount)",
        Filter(Filter(SCAN, AMOUNT_GT_40), REGION_EU),
        False,
        ["merge filters"],
    ),
    (
        "limit below projection",
        Limit(Project(Sort(SCAN, BY_ID), PASS_THROUGH_WITH_DERIVED), 3),
        True,
        ["limit below projection"],
    ),
    (
        "limit never moves below a sort",
        Limit(Sort(SCAN, BY_ID), 2),
        True,
        [],
    ),
    (
        "limit never moves below a filter (the filter itself still lowers below the sort)",
        Limit(Filter(Sort(SCAN, BY_ID), REGION_EU), 2),
        True,
        ["filter below sort"],
    ),
    (
        "limit never moves below a distinct",
        Limit(Distinct(Sort(SCAN, BY_ID), (), "any"), 2),
        False,
        [],
    ),
    (
        "two limits merge: [1,+4) then [1,+2) is [2,+2)",
        Limit(Limit(Sort(SCAN, BY_ID), 4, 1), 2, 1),
        True,
        ["merge limits"],
    ),
    (
        "two limits merge when the inner is unbounded",
        Limit(Limit(Sort(SCAN, BY_ID), None, 2), 3, 1),
        True,
        ["merge limits"],
    ),
    (
        "two limits merge when the outer overshoots the inner",
        Limit(Limit(Sort(SCAN, BY_ID), 3, 0), 10, 2),
        True,
        ["merge limits"],
    ),
    (
        "a chain: filter under sort under projection, then merge",
        Filter(
            Filter(Sort(Project(SCAN, PASS_THROUGH_WITH_DERIVED), BY_ID), AMOUNT_GT_40),
            REGION_EU,
        ),
        True,
        [
            "filter below sort",
            "filter below sort",
            "filter below projection",
            "filter below projection",
            "merge filters",
        ],
    ),
    (
        "nothing moves through an aggregate",
        Filter(
            Aggregate(
                SCAN,
                (("region", Column("region")),),
                (("total", Call("sum", (Column("amount"),))),),
            ),
            Call("gt", (Column("total"), Literal(100.0, FLOAT64))),
        ),
        False,
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "tree", "ordered", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_rewritten_tree_agrees_with_the_original_on_both_engines(
    name: str, tree: Node, ordered: bool, expected: list[str], db: sqlite3.Connection
) -> None:
    rewritten, applied = rewrite(tree)
    assert [entry.rule for entry in applied] == expected, [
        str(entry) for entry in applied
    ]
    if not expected:
        assert rewritten is tree

    frames = {
        "as written / pandas": execute(tree, FRAMES),
        "rewritten / pandas": execute(rewritten, FRAMES),
    }
    for label, candidate in (("as written", tree), ("rewritten", rewritten)):
        try:
            frames[f"{label} / sqlite"] = pd.read_sql_query(
                to_sql(candidate, "sqlite"), db
            )
        except Unsupported as exc:  # pragma: no cover - keeps the corpus honest
            pytest.skip(f"sqlite cannot express this tree: {exc}")

    reference_label, reference = next(iter(frames.items()))
    reference = _normalise(reference)
    for label, frame in frames.items():
        candidate = _normalise(frame)
        assert list(candidate.columns) == list(reference.columns), (name, label)
        if not ordered:
            candidate, ref = _sorted(candidate), _sorted(reference)
        else:
            ref = reference
        pd.testing.assert_frame_equal(
            candidate,
            ref,
            check_dtype=False,
            obj=f"{name}: {label} vs {reference_label}",
        )


def test_rewrite_is_idempotent() -> None:
    for _, tree, _, _ in CASES:
        once, _ = rewrite(tree)
        twice, again = rewrite(once)
        assert again == []
        assert twice == once


# ------------------------------------------------------------- the payoff

register_extension("rewrite_test_noop", lambda frame, config: frame)


def test_a_filter_written_after_a_local_step_now_reaches_the_source(
    db: sqlite3.Connection,
) -> None:
    """The reason this file exists: fewer rows cross the network."""
    from service_transformations.ir.surfaces import SourceSurface, Surface

    # A surface that can filter but cannot project: the projection is the wall.
    surface = SourceSurface(
        "filter-only",
        Surface.SQL_LIMITED,
        dialect="sqlite",
        supports_filter=True,
        supports_sort=True,
    )
    tree = Filter(Project(SCAN, PASS_THROUGH_WITH_DERIVED), AMOUNT_GT_40)

    as_written = plan(tree, surface=surface, optimise=False)
    assert as_written.pushed_count == 1, as_written.explain()  # the scan alone
    assert as_written.sql is None or "WHERE" not in as_written.sql.upper()

    optimised = plan(tree, surface=surface)
    assert [entry.rule for entry in optimised.rewrites] == ["filter below projection"]
    assert optimised.sql is not None and "WHERE" in optimised.sql.upper(), (
        optimised.explain()
    )
    assert optimised.pushed_count == 2  # scan + filter
    assert "rewritten first:" in optimised.explain()

    # And the two plans still produce the same rows.
    expected = _sorted(
        _normalise(
            execute_plan(
                as_written,
                frames=FRAMES,
                run_sql=lambda sql: pd.read_sql_query(sql, db),
            )
        )
    )
    actual = _sorted(
        _normalise(
            execute_plan(
                optimised, frames=FRAMES, run_sql=lambda sql: pd.read_sql_query(sql, db)
            )
        )
    )
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)


def test_a_limit_written_after_a_local_step_now_reaches_the_source() -> None:
    from service_transformations.ir.surfaces import SourceSurface, Surface

    surface = SourceSurface(
        "limit-only",
        Surface.SQL_LIMITED,
        dialect="sqlite",
        supports_limit=True,
        supports_sort=True,
    )
    tree = Limit(Project(Sort(SCAN, BY_ID), PASS_THROUGH_WITH_DERIVED), 3)

    as_written = plan(tree, surface=surface, optimise=False)
    assert as_written.sql is None or "LIMIT" not in as_written.sql.upper()

    optimised = plan(tree, surface=surface)
    assert [entry.rule for entry in optimised.rewrites] == ["limit below projection"]
    assert optimised.sql is not None and "LIMIT 3" in optimised.sql.upper(), (
        optimised.explain()
    )


def test_nothing_moves_through_an_extension() -> None:
    tree = Filter(Extension(SCAN, "rewrite_test_noop"), AMOUNT_GT_40)
    rewritten, applied = rewrite(tree)
    assert applied == []
    assert rewritten is tree


def test_the_preview_plan_reports_rewrites_in_words() -> None:
    """What the Studio panel shows: the rule and what moved, not a node dump."""
    tree = Filter(Project(SCAN, PASS_THROUGH_WITH_DERIVED), AMOUNT_GT_40)
    result = plan(tree, "postgresql")
    assert len(result.rewrites) == 1
    text = str(result.rewrites[0])
    assert text.startswith("filter below projection: ")
    assert "now runs before Project(" in text
