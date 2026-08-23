from __future__ import annotations

import pytest

from service_extraction.sql_safety import MAX_QUERY_LENGTH, ensure_read_only_select, strip_sql_noise
from shared_python.errors import BadRequestError


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM orders",
        "select id, name from customers where active = true",
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        "SELECT * FROM orders;",
        "SELECT REPLACE(name, 'a', 'b') FROM customers",
        "SELECT * FROM orders WHERE note = 'please delete this row'",
        "SELECT * FROM orders -- drop table orders",
        "SELECT count(*) FROM orders OFFSET 10",
    ],
)
def test_accepts_read_only_selects(query: str) -> None:
    assert ensure_read_only_select(query) == query.strip()


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "UPDATE orders SET total = 0",
        "INSERT INTO orders VALUES (1)",
        "TRUNCATE orders",
        "ALTER TABLE orders ADD COLUMN x int",
        "CREATE TABLE evil (id int)",
        "GRANT ALL ON orders TO public",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE '/etc/passwd' AS leak",
    ],
)
def test_rejects_write_statements(query: str) -> None:
    with pytest.raises(BadRequestError):
        ensure_read_only_select(query)


def test_rejects_stacked_statements() -> None:
    with pytest.raises(BadRequestError, match="single statement"):
        ensure_read_only_select("SELECT 1; DROP TABLE orders")


def test_rejects_data_modifying_cte() -> None:
    """PostgreSQL allows writes inside a CTE, so a leading WITH is not sufficient."""
    with pytest.raises(BadRequestError, match="DELETE"):
        ensure_read_only_select("WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone")


def test_rejects_select_into() -> None:
    with pytest.raises(BadRequestError, match="INTO"):
        ensure_read_only_select("SELECT * INTO copied_orders FROM orders")


def test_keyword_hidden_in_comment_does_not_pass_through() -> None:
    """A comment cannot smuggle a statement in, and cannot trip a false positive."""
    assert ensure_read_only_select("SELECT 1 /* drop table x */")


def test_rejects_write_hidden_after_comment() -> None:
    with pytest.raises(BadRequestError):
        ensure_read_only_select("SELECT 1; /* comment */ DELETE FROM orders")


def test_rejects_empty_query() -> None:
    with pytest.raises(BadRequestError, match="empty"):
        ensure_read_only_select("   ")


def test_rejects_overlong_query() -> None:
    with pytest.raises(BadRequestError, match="too long"):
        ensure_read_only_select("SELECT " + ("a" * (MAX_QUERY_LENGTH + 1)))


def test_strip_sql_noise_removes_literals_and_comments() -> None:
    cleaned = strip_sql_noise("SELECT 'drop table' -- delete\nFROM t")
    assert "drop table" not in cleaned
    assert "delete" not in cleaned
    assert "FROM t" in cleaned
