from __future__ import annotations

from unittest.mock import MagicMock, patch

from service_destinations.connectors.postgres import check_postgres_connection


@patch("service_destinations.connectors.postgres.psycopg.connect")
def test_postgres_success(mock_connect) -> None:
    conn = MagicMock()
    conn_ctx = MagicMock()
    conn_ctx.__enter__.return_value = conn
    conn_ctx.__exit__.return_value = False
    mock_connect.return_value = conn_ctx

    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    cur_ctx = MagicMock()
    cur_ctx.__enter__.return_value = cur
    cur_ctx.__exit__.return_value = False
    conn.cursor.return_value = cur_ctx

    ok, msg, latency, warns = check_postgres_connection(
        {
            "host": "localhost",
            "port": 5432,
            "database": "db",
            "username": "u",
            "password": "p",
        }
    )
    assert ok is True
    assert "success" in msg.lower() or "SELECT" in msg
    assert latency is not None
    assert warns == []


@patch("service_destinations.connectors.postgres.psycopg.connect")
def test_postgres_failure(mock_connect) -> None:
    import psycopg

    mock_connect.side_effect = psycopg.OperationalError("connection refused")

    ok, msg, latency, warns = check_postgres_connection(
        {
            "host": "localhost",
            "port": 5432,
            "database": "db",
            "username": "u",
            "password": "p",
        }
    )
    assert ok is False
    assert latency is None
    assert "refused" in msg.lower() or "Could not connect" in msg
