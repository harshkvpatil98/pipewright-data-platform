"""Pushdown wired into extraction runs (P9; the Phase 12 cutover).

The gate is differential: for a job with steps, the pushed split -- the
prefix the source ran as SQL around the job's query, plus what ran here on the
rows that came back -- must equal reading everything and running every step
locally. Pushdown rewrites the person's computation, so equality is the bar.
A real SQLite database stands in for the source, because SQLite is a SQL
surface the planner knows and the connector can read.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from service_extraction.connectors import sql_database
from service_extraction.shaping import (
    GRAIN_CHANGING,
    plan_job_steps,
    shape_rows,
    validate_job_steps,
    wrap_pushed_sql,
)
from service_transformations.executor import apply_transformation_steps
from shared_python.errors import BadRequestError

ROWS = [
    (1, "north", "web", 120.5, "2026-08-01"),
    (2, "south", "web", 89.99, "2026-08-01"),
    (3, "north", "store", None, "2026-08-02"),
    (4, "east", "web", 240.0, "2026-08-02"),
    (5, "south", "store", 55.25, "2026-08-03"),
    (6, "west", "web", 310.75, "2026-08-03"),
    (7, "north", "web", -15.0, "2026-08-04"),
]


@pytest.fixture()
def source(tmp_path: Path) -> dict[str, str]:
    db_path = tmp_path / "orders.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, channel TEXT, amount REAL, ordered_on TEXT)")
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", ROWS)
    conn.commit()
    conn.close()
    return {"file_path": str(db_path)}


BASE_QUERY = 'SELECT "id", "region", "channel", "amount", "ordered_on" FROM "orders"'


def _readers(config):
    def read_sql(sql: str) -> pd.DataFrame:
        return sql_database.read_dataframe("sqlite", config, sql=sql, validate_read_only=False).dataframe

    def read_all() -> pd.DataFrame:
        return sql_database.read_dataframe("sqlite", config, sql=BASE_QUERY).dataframe

    return read_sql, read_all


def _same(left: pd.DataFrame, right: pd.DataFrame) -> None:
    assert list(left.columns) == list(right.columns)
    l2 = left.astype("object").where(left.notna(), None).reset_index(drop=True)
    r2 = right.astype("object").where(right.notna(), None).reset_index(drop=True)
    pd.testing.assert_frame_equal(l2, r2, check_dtype=False)


PUSHABLE = [
    {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 0}]}},
    {"step_type": "select_columns", "config": {"columns": ["id", "region", "amount"]}},
    {"step_type": "rename_columns", "config": {"mappings": {"amount": "net"}}},
    {"step_type": "sort_rows", "config": {"columns": ["net"], "ascending": False}},
]

MIXED = [
    *PUSHABLE[:2],
    # split_column is an Extension: no SQL form, so it and everything after run here.
    {"step_type": "split_column", "config": {"column": "region", "delimiter": "o", "into": ["a", "b"]}},
    {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "less_than", "value": 300}]}},
]


def test_the_whole_recipe_is_pushed_when_the_source_can_run_it(source):
    read_sql, read_all = _readers(source)
    outcome = shape_rows(steps=PUSHABLE, connector_type="sqlite", base_query=BASE_QUERY,
                         read_sql=read_sql, read_all=read_all)
    assert outcome.plan["pushed_steps"] == len(PUSHABLE) and outcome.plan["local_steps"] == 0
    assert f"FROM ({BASE_QUERY})" in outcome.plan["sql"]
    # Differential: equals every step run locally over the plain extract.
    expected, _ = apply_transformation_steps(read_all(), PUSHABLE)
    _same(outcome.frame, expected)
    assert list(outcome.frame["net"]) == sorted(outcome.frame["net"], reverse=True)
    assert len(outcome.frame) == 5  # the null and the negative amount are gone


def test_a_prefix_is_pushed_and_the_rest_runs_here(source):
    read_sql, read_all = _readers(source)
    outcome = shape_rows(steps=MIXED, connector_type="sqlite", base_query=BASE_QUERY,
                         read_sql=read_sql, read_all=read_all)
    assert outcome.plan["pushed_steps"] == 2 and outcome.plan["local_steps"] == 2
    local_reasons = [p["reason"] for p in outcome.plan["placements"] if not p["pushed"]]
    assert any("extension" in r.lower() or "no sql" in r.lower() or "local" in r.lower() for r in local_reasons)
    expected, _ = apply_transformation_steps(read_all(), MIXED)
    _same(outcome.frame, expected)


def test_an_unknown_source_runs_everything_here_and_says_so(source):
    read_sql, read_all = _readers(source)
    outcome = shape_rows(steps=PUSHABLE, connector_type="mystery_api", base_query=BASE_QUERY,
                         read_sql=read_sql, read_all=read_all)
    assert outcome.plan["pushed_steps"] == 0 and outcome.plan["local_steps"] == len(PUSHABLE)
    assert outcome.plan["sql"] is None
    expected, _ = apply_transformation_steps(read_all(), PUSHABLE)
    _same(outcome.frame, expected)


def test_a_source_that_refuses_the_pushed_statement_falls_back_locally(source):
    _read_sql, read_all = _readers(source)

    def refusing(_sql: str) -> pd.DataFrame:
        raise RuntimeError("permission denied for relation orders")

    outcome = shape_rows(steps=PUSHABLE, connector_type="sqlite", base_query=BASE_QUERY,
                         read_sql=refusing, read_all=read_all)
    assert outcome.plan["pushed_steps"] == 0
    assert any("refused the pushed statement" in w for w in outcome.warnings)
    expected, _ = apply_transformation_steps(read_all(), PUSHABLE)
    _same(outcome.frame, expected)


def test_no_steps_means_a_plain_extract(source):
    read_sql, read_all = _readers(source)
    outcome = shape_rows(steps=[], connector_type="sqlite", base_query=BASE_QUERY,
                         read_sql=read_sql, read_all=read_all)
    assert outcome.plan is None and len(outcome.frame) == len(ROWS)


def test_wrapping_substitutes_the_scan_for_the_jobs_query():
    plan = plan_job_steps(PUSHABLE[:1], connector_type="sqlite", columns=["id", "amount"])
    wrapped = wrap_pushed_sql(plan.sql, "SELECT 1 AS id, 2 AS amount", dialect_quote=lambda s: f'"{s}"')
    assert 'FROM (SELECT 1 AS id, 2 AS amount) AS "__extract__"' in wrapped
    assert 'FROM "__extract__"' not in wrapped


def test_grain_changing_steps_are_refused_for_incremental_loads():
    aggregate = [{"step_type": "aggregate", "config": {"group_by": ["region"], "aggregations": [{"column": "amount", "function": "sum"}]}}]
    assert validate_job_steps(aggregate, load_mode="full_refresh")[0]["step_type"] == "aggregate"
    with pytest.raises(BadRequestError, match="incremental load"):
        validate_job_steps(aggregate, load_mode="incremental_append")
    # Row-wise steps are fine on a slice.
    assert len(validate_job_steps(PUSHABLE[:3], load_mode="incremental_append")) == 3
    assert "aggregate" in GRAIN_CHANGING and "filter_rows" not in GRAIN_CHANGING


def test_steps_are_validated_at_save_time():
    with pytest.raises(BadRequestError):
        validate_job_steps([{"step_type": "teleport", "config": {}}], load_mode="full_refresh")
    assert validate_job_steps(None, load_mode="full_refresh") == []
