"""Statistics for tables in connected databases (D2, O1).

PostgreSQL describes its tables from its own statistics, reading none of
the rows; anything else from the first rows it returns. Either way the
numbers say how they were got, and an estimate built on them lands near
the truth. The PostgreSQL and MySQL cases need the servers from
`docker-compose.connectors.yml` and skip without them.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_extraction import table_statistics
from service_extraction.connectors import sql_database
from service_extraction.extract import run_extraction_job
from service_extraction.models import ExtractionConnection, ExtractionJob, TableStatistics
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.security.config_crypto import encrypt_sensitive_fields
from shared_python.statistics import TableStats
from shared_python.storage.local import LocalStorageBackend

POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
MYSQL = os.environ.get("CONNECTORS_TEST_MYSQL_URL")
OWNER_ID = uuid.UUID("0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f")
SETTINGS = SimpleNamespace(max_upload_size_bytes=25 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)
ROWS = 3_000


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def shop(tmp_path) -> str:
    """A SQLite file with ROWS orders: `region` four values, one far commoner; `amount` 0 to 2,999."""
    path = str(tmp_path / "shop.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, amount REAL, note TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            (i, "north" if i % 10 < 7 else ("south", "east", "west")[i % 3], float(i), None if i % 4 == 0 else "x")
            for i in range(ROWS)
        ])
    return path


@pytest.fixture()
def world(db: Session, shop: str, tmp_path) -> dict:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.flush()
    project = Project(name="Shop", slug="shop", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()
    connection = ExtractionConnection(project_id=project.id, name="Shop DB", connector_type="sqlite",
                                      config_json={"file_path": shop})
    db.add(connection)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    return {"project": project, "connection": connection, "user": user,
            "storage": LocalStorageBackend(str(tmp_path / "storage"))}


def _server(db: Session, world: dict, kind: str, url: str) -> ExtractionConnection:
    parsed = make_url(url)
    config = {"host": parsed.host, "port": parsed.port, "database": parsed.database,
              "username": parsed.username, "password": parsed.password}
    connection = ExtractionConnection(project_id=world["project"].id, name=kind, connector_type=kind,
                                      config_json=encrypt_sensitive_fields(config, ("password",)))
    db.add(connection)
    db.commit()
    return connection


def _fill(url: str, table: str, *, analyse: bool) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, region VARCHAR(16), amount FLOAT, "
                              "placed DATE)"))
            rows = [{"id": i, "region": "north" if i % 10 < 7 else ("south", "east", "west")[i % 3],
                     "amount": float(i), "placed": (datetime(2026, 1, 1) + timedelta(days=i % 300)).date()}
                    for i in range(ROWS)]
            conn.execute(text(f"INSERT INTO {table} VALUES (:id, :region, :amount, :placed)"), rows)
            if analyse:
                conn.execute(text(f"ANALYZE {'TABLE ' if url.startswith('mysql') else ''}{table}"))
    finally:
        engine.dispose()


def _estimate(stats: TableStats, predicate) -> float:
    from service_transformations.ir.estimate import estimate
    from service_transformations.ir.nodes import Filter, Scan
    from shared_python.types import FLOAT64, STRING

    scan = Scan("orders", tuple((name, FLOAT64 if name == "amount" else STRING) for name in stats.columns))
    return estimate(Filter(scan, predicate), {"orders": stats}).rows


def _region_is(value: str):
    from service_transformations.ir.expressions import Call, Column, Literal
    from shared_python.types import STRING

    return Call("eq", (Column("region"), Literal(value, STRING)))


def _amount_below(value: float):
    from service_transformations.ir.expressions import Call, Column, Literal
    from shared_python.types import FLOAT64

    return Call("lt", (Column("amount"), Literal(value, FLOAT64)))


# ---------------------------------------------------------------- SQLite


def test_a_small_table_is_described_from_every_row(db: Session, world: dict) -> None:
    stats = table_statistics.collect(world["connection"], None, "orders")
    assert stats.method == "every row"
    assert stats.rows == ROWS
    assert stats.columns["region"].distinct == 4
    assert stats.columns["note"].empty_share == pytest.approx(0.25)
    assert ("north", 2_100) in stats.columns["region"].common
    # The estimate built on it is close to the truth: 70% north, a third below 1,000.
    assert _estimate(stats, _region_is("north")) == pytest.approx(2_100, rel=0.02)
    assert _estimate(stats, _amount_below(1_000.0)) == pytest.approx(1_000, rel=0.05)


def test_a_large_table_is_described_from_its_first_rows_and_says_so(db: Session, world: dict, monkeypatch) -> None:
    monkeypatch.setattr(table_statistics, "SAMPLE_ROWS", 1_000)
    stats = table_statistics.collect(world["connection"], None, "orders")
    assert stats.method == "the first 1,000 rows"
    assert stats.rows == ROWS  # counted, not the sample's size
    # A key nearly every row differs in grows with the table; a column of four values does not.
    assert stats.columns["id"].distinct == pytest.approx(ROWS, rel=0.01)
    assert stats.columns["region"].distinct == 4
    assert _estimate(stats, _region_is("north")) == pytest.approx(2_100, rel=0.05)


def test_statistics_are_stored_kept_while_fresh_and_collected_again_when_old(db: Session, world: dict) -> None:
    connection = world["connection"]
    first = table_statistics.for_table(db, connection, None, "orders")
    assert first is not None and first.rows == ROWS
    row = table_statistics.stored(db, connection.id, None, "orders")
    assert row is not None and row.schema_name == "" and row.row_count == ROWS

    with sqlite3.connect(connection.config_json["file_path"]) as conn:
        conn.execute("DELETE FROM orders WHERE id >= 1000")
    assert table_statistics.for_table(db, connection, None, "orders").rows == ROWS  # still fresh

    row.collected_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()
    assert table_statistics.for_table(db, connection, None, "orders").rows == 1_000
    assert db.scalar(select(func.count()).select_from(TableStatistics)) == 1


def test_a_table_that_cannot_be_read_gives_no_statistics_rather_than_an_error(db: Session, world: dict) -> None:
    assert table_statistics.for_table(db, world["connection"], None, "no_such_table") is None


def test_the_api_reads_and_collects_again_and_refuses_a_source_that_is_not_a_database(db: Session, world: dict) -> None:
    project_id, connection = world["project"].id, world["connection"]
    read = table_statistics.read_model(db, project_id, connection.id, table="orders", schema=None,
                                       current_user=world["user"])
    assert read.rows == ROWS and read.method == "every row"
    assert {column.name for column in read.columns} == {"id", "region", "amount", "note"}
    region = next(column for column in read.columns if column.name == "region")
    assert region.common[0] == ("north", 2_100)
    amount = next(column for column in read.columns if column.name == "amount")
    assert len(amount.bounds) == len(amount.bucket_rows) + 1 and sum(amount.bucket_rows) == ROWS

    with sqlite3.connect(connection.config_json["file_path"]) as conn:
        conn.execute("DELETE FROM orders WHERE id >= 10")
    again = table_statistics.read_model(db, project_id, connection.id, table="orders", schema=None,
                                        current_user=world["user"], fresh=True)
    assert again.rows == 10 and again.collected_at >= read.collected_at

    files = ExtractionConnection(project_id=project_id, name="Files", connector_type="s3", config_json={})
    db.add(files)
    db.commit()
    with pytest.raises(BadRequestError, match="not a database"):
        table_statistics.read_model(db, project_id, files.id, table="orders", schema=None, current_user=world["user"])


def test_an_import_of_a_table_collects_its_statistics(db: Session, world: dict) -> None:
    job = ExtractionJob(project_id=world["project"].id, connection_id=world["connection"].id, name="Orders",
                        source_kind="table", source_table="orders", load_mode="full_refresh")
    db.add(job)
    db.commit()
    run_extraction_job(db, project_id=world["project"].id, job_id=job.id, current_user=world["user"],
                       storage_backend=world["storage"], settings=SETTINGS)
    row = table_statistics.stored(db, world["connection"].id, None, "orders")
    assert row is not None and row.row_count == ROWS


def test_the_daily_pass_refreshes_only_old_statistics_of_tables_imports_read(db: Session, world: dict) -> None:
    connection = world["connection"]
    db.add(ExtractionJob(project_id=world["project"].id, connection_id=connection.id, name="Orders",
                         source_kind="table", source_table="orders", load_mode="full_refresh"))
    db.add(ExtractionJob(project_id=world["project"].id, connection_id=connection.id, name="Orders again",
                         source_kind="table", source_table="orders", load_mode="full_refresh"))
    db.add(ExtractionJob(project_id=world["project"].id, connection_id=connection.id, name="By query",
                         source_kind="query", query_sql="SELECT 1"))
    db.commit()
    assert table_statistics.refresh_due(db) == 1  # one table, read by two imports
    assert table_statistics.refresh_due(db) == 0  # fresh now
    table_statistics.stored(db, connection.id, None, "orders").collected_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()
    assert table_statistics.refresh_due(db) == 1


def test_refreshing_needs_an_editor_and_reading_a_viewer() -> None:
    from service_access.permissions import required_role

    base = "/api/v1/projects/p/extraction/connections/c/statistics"
    assert required_role("GET", base) == "viewer"
    assert required_role("POST", base + "/refresh") == "editor"


# ------------------------------------------------------------ the parsers


def test_postgresql_arrays_and_bounds_are_read_as_written() -> None:
    assert table_statistics._pg_array('{north,"south east",NULL,"NULL","a\\"b"}') == [
        "north", "south east", None, "NULL", 'a"b']
    assert table_statistics._pg_array(None) == []
    assert table_statistics._pg_array("{}") == []
    assert table_statistics._edges(["1", "2.5", "10"]) == ("number", [1.0, 2.5, 10.0])
    kind, edges = table_statistics._edges(["2026-01-01", "2026-01-02"])
    assert kind == "datetime" and edges[1] - edges[0] == 86_400_000
    assert table_statistics._edges(["2026-01-01 00:00:00+00", "2026-01-01 01:00:00+00"])[0] == "datetime"
    assert table_statistics._edges(["apple", "pear"]) == ("text", [])


# ------------------------------------------------------- real databases


@pytest.mark.skipif(not POSTGRES, reason="Set CONNECTORS_TEST_POSTGRES_URL to read PostgreSQL's own statistics.")
def test_postgresql_tables_are_described_from_its_own_statistics(db: Session, world: dict) -> None:
    from service_transformations.ir.expressions import Call, Column, Literal
    from shared_python.types import STRING

    table = f"stats_{uuid.uuid4().hex[:8]}"
    connection = _server(db, world, "postgresql", POSTGRES)
    try:
        _fill(POSTGRES, table, analyse=False)
        # Never analysed: there is nothing of PostgreSQL's own to use yet, so a sample.
        assert table_statistics.collect(connection, None, table).method == "every row"

        _fill(POSTGRES, table, analyse=True)
        stats = table_statistics.collect(connection, None, table)
        assert stats.method == "PostgreSQL's own statistics"
        assert stats.rows == ROWS
        assert stats.columns["region"].distinct == 4
        assert stats.columns["id"].distinct == ROWS  # n_distinct -1: every row differs
        assert stats.columns["placed"].kind == "datetime"
        assert _estimate(stats, _region_is("north")) == pytest.approx(2_100, rel=0.05)
        assert _estimate(stats, _amount_below(1_000.0)) == pytest.approx(1_000, rel=0.1)
        # A date range: about a third of the days in the year's first 300.
        placed = Call("lt", (Column("placed"), Literal("2026-04-11", STRING)))
        assert _estimate(stats, placed) == pytest.approx(ROWS * 100 / 300, rel=0.1)
    finally:
        # The connection's pooled engine may still hold the table; let go of it before dropping.
        sql_database.dispose_cached_engines()
        engine = create_engine(POSTGRES)
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


@pytest.mark.skipif(not MYSQL, reason="Set CONNECTORS_TEST_MYSQL_URL to read MySQL's row count.")
def test_mysql_tables_are_described_from_their_first_rows_and_its_row_count(db: Session, world: dict,
                                                                             monkeypatch) -> None:
    monkeypatch.setattr(table_statistics, "SAMPLE_ROWS", 1_000)
    table = f"stats_{uuid.uuid4().hex[:8]}"
    connection = _server(db, world, "mysql", MYSQL)
    try:
        _fill(MYSQL, table, analyse=True)
        stats = table_statistics.collect(connection, None, table)
        assert stats.method == "the first 1,000 rows"
        # TABLE_ROWS is MySQL's own estimate: near, not exact.
        assert stats.rows == pytest.approx(ROWS, rel=0.25)
        assert stats.columns["region"].distinct == 4
    finally:
        # The connection's pooled engine may still hold the table; let go of it before dropping.
        sql_database.dispose_cached_engines()
        engine = create_engine(MYSQL)
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


@pytest.mark.skipif(not MYSQL, reason="Set CONNECTORS_TEST_MYSQL_URL to read from MySQL.")
def test_a_mysql_read_that_stops_at_its_limit_leaves_nothing_to_drain(db: Session, world: dict) -> None:
    """Stopping early used to leave the rest of the result for the next use of the connection to read."""
    import warnings

    parsed = make_url(MYSQL)
    config = {"host": parsed.host, "port": parsed.port, "database": parsed.database,
              "username": parsed.username, "password": parsed.password}
    table = f"stats_{uuid.uuid4().hex[:8]}"
    try:
        _fill(MYSQL, table, analyse=False)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            read = sql_database.read_dataframe("mysql", config, sql=f"SELECT * FROM {table}", max_rows=100,
                                               chunk_size=50)
            assert read.truncated and read.row_count == 100
            again = sql_database.read_dataframe("mysql", config, sql=f"SELECT COUNT(*) AS n FROM {table}")
            assert int(again.dataframe["n"][0]) == ROWS
    finally:
        sql_database.dispose_cached_engines()
        engine = create_engine(MYSQL)
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()
