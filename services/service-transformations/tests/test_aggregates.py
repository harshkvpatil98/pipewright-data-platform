"""Every aggregate the step offers, checked three ways.

1. The step and the IR give the same rows (`ir/pandas_aggregates.py` is the
   one implementation both call).
2. Known answers, including SQL's rules for empty values: skipped, and a
   group with none at all comes to nothing.
3. The ones that lower to SQL give the same numbers in SQLite and, when
   `CONNECTORS_TEST_POSTGRES_URL` is set, in PostgreSQL.

Before E1, `variance`, `string_agg`, `any_true`, `all_true` and `product` were
declared in the IR's catalogue with no pandas implementation at all, so any
tree using them failed at run time; the step never offered them.
"""

from __future__ import annotations

import os
import sqlite3
import uuid

import pandas as pd
import pytest

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING

from service_transformations.executor import apply_single_step as _apply_step
from service_transformations.schemas import TransformationStep
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.from_steps import compile_step
from service_transformations.ir.nodes import Aggregate, Scan
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import Unsupported, to_sql
from service_transformations.steps.aggregate import EXTRA_AGGREGATIONS, apply_aggregate

FRAME = pd.DataFrame({
    "team": ["a", "a", "a", "b", "b", "c", None],
    "score": [1.0, 2.0, 4.0, 10.0, None, None, 7.0],
    "weight": [1.0, 1.0, 2.0, 3.0, 1.0, 1.0, 1.0],
    "won": [True, False, True, False, None, None, True],
    "name": ["x", "y", "x", "p", "q", None, "z"],
})

SCAN = Scan("t", (("team", STRING), ("score", FLOAT64), ("weight", FLOAT64), ("won", BOOLEAN), ("name", STRING)))


def apply_single_step(frame: pd.DataFrame, step_type: str, config: dict):
    return _apply_step(frame, TransformationStep(step_type=step_type, config=config))


def step(function: str, column: str = "score", **extra) -> dict:
    return {"group_by": ["team"], "aggregations": [{"column": column, "function": function, "alias": "v", **extra}]}


CASES = [
    ("variance", "score", {}),
    ("mode", "name", {}),
    ("count_empty", "score", {}),
    ("nth", "name", {"argument": 2}),
    ("list", "name", {}),
    ("join_text", "name", {"argument": " / "}),
    ("percentile", "score", {"argument": 90}),
    ("first_quartile", "score", {}),
    ("third_quartile", "score", {}),
    ("range", "score", {}),
    ("product", "score", {}),
    ("any_true", "won", {}),
    ("all_true", "won", {}),
    ("correlation", "score", {"other_column": "weight"}),
    ("covariance", "score", {"other_column": "weight"}),
    ("weighted_average", "score", {"other_column": "weight"}),
]


def values(frame: pd.DataFrame) -> dict:
    return {(None if pd.isna(k) else k): (None if v is None or (not isinstance(v, str) and pd.isna(v))
                                          else round(v, 9) if isinstance(v, float) else v)
            for k, v in zip(frame["team"], frame["v"])}


def test_every_new_function_is_covered_here() -> None:
    assert {name for name, _, _ in CASES} == set(EXTRA_AGGREGATIONS)


@pytest.mark.parametrize(("function", "column", "extra"), CASES, ids=[c[0] for c in CASES])
def test_the_step_and_the_ir_agree(function: str, column: str, extra: dict) -> None:
    config = step(function, column, **extra)
    legacy, _ = apply_aggregate(FRAME, config)
    through_ir, _ = apply_single_step(FRAME, "aggregate", config)
    assert values(legacy) == values(through_ir)


@pytest.mark.parametrize(("function", "column", "extra", "expected"), [
    ("variance", "score", {}, {"a": 2.333333333, "b": None, "c": None, None: None}),
    ("mode", "name", {}, {"a": "x", "b": "p", "c": None, None: "z"}),
    ("count_empty", "score", {}, {"a": 0, "b": 1, "c": 1, None: 0}),
    ("nth", "name", {"argument": 2}, {"a": "y", "b": "q", "c": None, None: None}),
    ("list", "name", {}, {"a": '["x", "y", "x"]', "b": '["p", "q"]', "c": None, None: '["z"]'}),
    ("join_text", "name", {"argument": " / "}, {"a": "x / y / x", "b": "p / q", "c": None, None: "z"}),
    ("percentile", "score", {"argument": 90}, {"a": 3.6, "b": 10.0, "c": None, None: 7.0}),
    ("first_quartile", "score", {}, {"a": 1.5, "b": 10.0, "c": None, None: 7.0}),
    ("range", "score", {}, {"a": 3.0, "b": 0.0, "c": None, None: 0.0}),
    ("product", "score", {}, {"a": 8.0, "b": 10.0, "c": None, None: 7.0}),
    ("any_true", "won", {}, {"a": True, "b": False, "c": None, None: True}),
    ("all_true", "won", {}, {"a": False, "b": False, "c": None, None: True}),
    ("weighted_average", "score", {"other_column": "weight"}, {"a": 2.75, "b": 10.0, "c": None, None: 7.0}),
])
def test_known_answers(function: str, column: str, extra: dict, expected: dict) -> None:
    out, _ = apply_single_step(FRAME, "aggregate", step(function, column, **extra))
    assert values(out) == expected


def test_a_percentile_outside_0_to_100_is_refused() -> None:
    with pytest.raises(BadRequestError, match="between 0 and 100"):
        apply_single_step(FRAME, "aggregate", step("percentile", argument=120))


def test_a_correlation_names_its_second_column() -> None:
    with pytest.raises(BadRequestError, match="other_column"):
        apply_single_step(FRAME, "aggregate", step("correlation"))


def test_lineage_follows_the_second_column() -> None:
    from service_lineage.columns import build_pipeline_lineage

    lineage = build_pipeline_lineage(base_columns=list(FRAME.columns), steps=[
        {"step_type": "aggregate", "config": step("weighted_average", other_column="weight")}])
    sources = {edge.from_column for edge in lineage.steps[-1].edges if edge.to_column == "v"}
    assert sources == {"score", "weight"}


# -------------------------------------------------------------- in databases

PUSHED = [
    ("count_null", (Column("score"),)),
    ("range", (Column("score"),)),
    ("weighted_avg", (Column("score"), Column("weight"))),
    ("median", (Column("score"),)),
    ("percentile", (Column("score"), Literal(0.9, FLOAT64))),
    ("percentile", (Column("score"), Literal(0.25, FLOAT64))),
    ("corr", (Column("score"), Column("weight"))),
    ("covar", (Column("score"), Column("weight"))),
    ("variance", (Column("score"),)),
    ("stddev", (Column("score"),)),
    ("any_true", (Column("won"),)),
    ("all_true", (Column("won"),)),
]


def tree(function: str, args) -> Aggregate:
    return Aggregate(SCAN, group_by=(("team", Column("team")),), aggregates=(("v", Call(function, args)),))


def _check(function: str, args, dialect: str, connection) -> None:
    node = tree(function, args)
    try:
        sql = to_sql(node, dialect)
    except Unsupported:
        pytest.skip(f"{function} does not lower to {dialect}")
    if not isinstance(connection, sqlite3.Connection):
        from sqlalchemy import text

        sql = text(sql)
    remote = pd.read_sql_query(sql, connection)
    local = execute(node, {"t": FRAME})
    assert values(local) == values(remote), function


@pytest.fixture(scope="module")
def sqlite_db():
    connection = sqlite3.connect(":memory:")
    FRAME.to_sql("t", connection, index=False)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def postgres_db():
    url = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("CONNECTORS_TEST_POSTGRES_URL is not set")
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    schema = f"aggregates_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
        FRAME.to_sql("t", connection, index=False)
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    yield connection
    connection.close()
    with engine.begin() as cleanup:
        cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.mark.parametrize(("function", "args"), PUSHED, ids=[f"{f}-{i}" for i, (f, _) in enumerate(PUSHED)])
def test_sqlite_agrees(function: str, args, sqlite_db) -> None:
    _check(function, args, "sqlite", sqlite_db)


@pytest.mark.parametrize(("function", "args"), PUSHED, ids=[f"{f}-{i}" for i, (f, _) in enumerate(PUSHED)])
def test_postgres_agrees(function: str, args, postgres_db) -> None:
    _check(function, args, "postgres", postgres_db)


def test_postgres_lowers_every_function_it_says_it_does() -> None:
    for function, args in PUSHED:
        to_sql(tree(function, args), "postgres")


@pytest.mark.parametrize("function", ["mode", "nth", "list_agg", "string_agg", "first", "last"])
def test_an_answer_that_depends_on_row_order_stays_here(function: str) -> None:
    args = (Column("name"), Literal(2, INT64)) if function == "nth" else (Column("name"),)
    for dialect in ("postgres", "sqlite", "mysql", "duckdb"):
        with pytest.raises(Unsupported):
            to_sql(tree(function, args), dialect)


def test_compiling_the_step_gives_the_ir_call() -> None:
    node = compile_step(SCAN, "aggregate", step("percentile", argument=90))
    assert node.aggregates[0][1] == Call("percentile", (Column("score"), Literal(0.9, FLOAT64)))
