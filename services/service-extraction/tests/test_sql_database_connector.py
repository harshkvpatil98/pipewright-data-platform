"""Connector tests against a real SQLite file.

SQLite goes through the same SQLAlchemy path as PostgreSQL and MySQL, so these
exercise genuine connect/discover/read behaviour rather than mocks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from service_extraction.connectors import sql_database
from service_extraction.incremental import build_incremental_query
from shared_python.errors import BadRequestError


@pytest.fixture()
def sqlite_config(tmp_path: Path) -> Iterator[dict[str, str]]:
    db_path = tmp_path / "warehouse.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer TEXT NOT NULL,
            total REAL,
            updated_at TEXT
        );
        INSERT INTO orders (id, customer, total, updated_at) VALUES
            (1, 'alpha', 10.5, '2026-01-01'),
            (2, 'beta',  20.0, '2026-02-01'),
            (3, 'gamma', 30.25,'2026-03-01');
        CREATE VIEW recent_orders AS SELECT * FROM orders WHERE id > 1;
        """
    )
    conn.commit()
    conn.close()

    yield {"file_path": str(db_path)}
    sql_database.dispose_cached_engines()


def test_connection_succeeds_and_reports_version(sqlite_config: dict[str, str]) -> None:
    result = sql_database.test_connection("sqlite", sqlite_config)
    assert result.success is True
    assert result.latency_ms is not None
    assert result.server_version


def test_connection_failure_is_reported_not_raised(tmp_path: Path) -> None:
    """Testing a connection reports the problem; it never raises at the caller."""
    result = sql_database.test_connection(
        "sqlite", {"file_path": str(tmp_path / "nested" / "missing.db")}
    )
    assert result.success is False
    # The message names the actual cause rather than a generic connection error.
    assert "No SQLite database exists" in result.message


def test_lists_tables_and_views(sqlite_config: dict[str, str]) -> None:
    refs = sql_database.list_tables("sqlite", sqlite_config)
    by_name = {ref.name: ref for ref in refs}
    assert by_name["orders"].kind == "table"
    assert by_name["recent_orders"].kind == "view"


def test_lists_columns_with_primary_key(sqlite_config: dict[str, str]) -> None:
    columns = sql_database.list_columns("sqlite", sqlite_config, table="orders")
    by_name = {column.name: column for column in columns}
    assert by_name["id"].primary_key is True
    assert by_name["customer"].nullable is False
    assert by_name["total"].primary_key is False


def test_describing_unknown_table_raises(sqlite_config: dict[str, str]) -> None:
    with pytest.raises(BadRequestError):
        sql_database.list_columns("sqlite", sqlite_config, table="does_not_exist")


def test_reads_full_table(sqlite_config: dict[str, str]) -> None:
    query = sql_database.build_table_query("sqlite", table="orders", schema=None)
    result = sql_database.read_dataframe("sqlite", sqlite_config, sql=query)
    assert result.row_count == 3
    assert result.truncated is False
    assert list(result.dataframe.columns) == ["id", "customer", "total", "updated_at"]


def test_row_cap_truncates_and_warns(sqlite_config: dict[str, str]) -> None:
    result = sql_database.read_dataframe(
        "sqlite", sqlite_config, sql="SELECT * FROM orders", max_rows=2, chunk_size=1
    )
    assert result.row_count == 2
    assert result.truncated is True
    assert any("truncated" in warning.lower() for warning in result.warnings)


def test_chunked_read_returns_every_row(sqlite_config: dict[str, str]) -> None:
    """Chunk size below the result size must not drop or duplicate rows."""
    result = sql_database.read_dataframe("sqlite", sqlite_config, sql="SELECT * FROM orders", chunk_size=1)
    assert result.dataframe["id"].tolist() == [1, 2, 3]


def test_write_query_is_rejected_before_execution(sqlite_config: dict[str, str]) -> None:
    with pytest.raises(BadRequestError):
        sql_database.read_dataframe("sqlite", sqlite_config, sql="DELETE FROM orders")

    # The table is untouched because validation happens before the driver is reached.
    result = sql_database.read_dataframe("sqlite", sqlite_config, sql="SELECT * FROM orders")
    assert result.row_count == 3


def test_incremental_query_filters_by_watermark(sqlite_config: dict[str, str]) -> None:
    base = sql_database.build_table_query("sqlite", table="orders", schema=None)
    statement, params = build_incremental_query(
        "sqlite", base_query=base, cursor_column="updated_at", watermark="2026-01-01"
    )
    result = sql_database.read_dataframe(
        "sqlite", sqlite_config, sql=statement, params=params, validate_read_only=False
    )
    assert result.dataframe["id"].tolist() == [2, 3]


def test_empty_result_warns(sqlite_config: dict[str, str]) -> None:
    result = sql_database.read_dataframe("sqlite", sqlite_config, sql="SELECT * FROM orders WHERE id > 999")
    assert result.row_count == 0
    assert any("no rows" in warning.lower() for warning in result.warnings)


def test_engine_is_cached_between_calls(sqlite_config: dict[str, str]) -> None:
    first = sql_database.get_engine("sqlite", sqlite_config)
    second = sql_database.get_engine("sqlite", sqlite_config)
    assert first is second


def test_unsupported_connector_type_is_rejected() -> None:
    with pytest.raises(BadRequestError, match="Unsupported connector type"):
        sql_database.build_url("oracle", {"host": "h", "database": "d", "username": "u"})


def test_relative_sqlite_path_is_rejected() -> None:
    """A relative path resolves against the server's cwd, not the caller's."""
    with pytest.raises(BadRequestError, match="must be absolute"):
        sql_database.build_url("sqlite", {"file_path": "data/warehouse.db"})


def test_missing_sqlite_file_is_reported_not_created(tmp_path: Path) -> None:
    """SQLite would otherwise create an empty database and fail confusingly later."""
    missing = tmp_path / "not-there.db"
    with pytest.raises(BadRequestError, match="No SQLite database exists"):
        sql_database.build_url("sqlite", {"file_path": str(missing)})
    assert not missing.exists()


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(BadRequestError, match="host"):
        sql_database.build_url("postgresql", {"database": "d", "username": "u"})


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(BadRequestError, match="port"):
        sql_database.build_url(
            "postgresql", {"host": "h", "database": "d", "username": "u", "port": 99999}
        )
