"""Every tool that pushes down gives the same answer in the database (E1).

`test_tool_pushdown.py` proves a pushable tool compiles to SQL; this runs that
SQL. Each tool's documented example is loaded into SQLite (and PostgreSQL,
when `CONNECTORS_TEST_POSTGRES_URL` names one, as CI does), its node is
compiled for that dialect where the planner would push it, and the rows that
come back must equal the rows the local engine gives, value for value.
"""

from __future__ import annotations

import os
import sqlite3
import uuid

import numpy as np
import pandas as pd
import pytest

import service_transformations.tools as tools
from service_transformations.ir.nodes import Limit, Node, Sort, pushable_to
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import Unsupported, to_sql
from service_transformations.tools.apply import SOURCE, build


def _frame(spec: tools.ToolSpec) -> pd.DataFrame:
    return pd.DataFrame(list(spec.example.rows))


def _config(spec: tools.ToolSpec, frame: pd.DataFrame) -> dict:
    column = spec.example.column or (list(frame.columns)[0] if len(frame.columns) else None)
    config = {"tool": spec.name, **spec.example.params}
    if column is not None:
        config["column"] = column
    return config


def _pushable(dialect: str) -> list[str]:
    names = []
    for name, spec in sorted(tools.TOOLS.items()):
        if spec.local_only or spec.reads_dataset:
            continue
        frame = _frame(spec)
        try:
            node = build(frame, _config(spec, frame))
        except Exception:  # noqa: BLE001 - a tool that will not build is the harness's business
            continue
        if all(pushable_to(dialect, part) for part in node.walk()):
            try:
                to_sql(node, dialect)
            except Unsupported:
                continue
            names.append(name)
    return names


def _normalise(frame: pd.DataFrame) -> list[tuple]:
    def plain(value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return None
        from decimal import Decimal

        if isinstance(value, (bool, np.bool_)):
            return int(value)
        if isinstance(value, (int, float, np.integer, np.floating, Decimal)):
            return round(float(value), 6)
        return str(value)

    return [tuple(plain(v) for v in row) for row in frame.itertuples(index=False, name=None)]


def _agree(name: str, dialect: str, connection, table: str) -> None:
    spec = tools.TOOLS[name]
    frame = _frame(spec)
    node: Node = build(frame, _config(spec, frame))
    sql = to_sql(node, dialect).replace(f'"{SOURCE}"', f'"{table}"')
    if not isinstance(connection, sqlite3.Connection):
        from sqlalchemy import text

        frame.to_sql(table, connection, index=False, if_exists="replace")
        remote = pd.read_sql_query(text(sql), connection)
    else:
        frame.to_sql(table, connection, index=False, if_exists="replace")
        remote = pd.read_sql_query(sql, connection)
    local = execute(node, {SOURCE: frame})
    assert list(remote.columns) == list(local.columns), f"{name}\n{sql}"
    got, wanted = _normalise(remote), _normalise(local)
    if not isinstance(node, (Sort, Limit)):
        # SQL promises no order without its own ORDER BY: compare the rows.
        got, wanted = sorted(got, key=repr), sorted(wanted, key=repr)
    assert got == wanted, f"{name}: the database and the engine disagree\n{sql}"


SQLITE = _pushable("sqlite")
POSTGRES = _pushable("postgres")


def test_a_real_share_of_the_library_pushes_down() -> None:
    assert len(SQLITE) >= 40 and len(POSTGRES) >= 60, (len(SQLITE), len(POSTGRES))


@pytest.fixture(scope="module")
def sqlite_db():
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def postgres_db():
    url = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("CONNECTORS_TEST_POSTGRES_URL is not set")
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    schema = f"tools_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    connection.commit()
    yield connection
    connection.close()
    with engine.begin() as cleanup:
        cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.mark.parametrize("name", SQLITE)
def test_sqlite_gives_the_same_answer(name: str, sqlite_db) -> None:
    _agree(name, "sqlite", sqlite_db, "example")


@pytest.mark.parametrize("name", POSTGRES)
def test_postgres_gives_the_same_answer(name: str, postgres_db) -> None:
    try:
        _agree(name, "postgres", postgres_db, "example")
    except Exception:
        postgres_db.rollback()
        raise
    postgres_db.commit()
