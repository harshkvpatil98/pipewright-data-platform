"""Schema browsing and autocomplete.

The useful part of completion is the narrowing, so most of these tests are about
what is *not* offered: a column list after `FROM` is a list nobody reads.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from shared_python.errors import BadRequestError
from service_workbench.completion import Context, complete, read_cursor, tables_in_scope
from service_workbench.schema_tree import forget, load_columns, snapshot


@pytest.fixture()
def engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE orders ("
                "  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,"
                "  region TEXT, amount REAL)"
            )
        )
        connection.execute(
            sa.text("CREATE TABLE customers (id INTEGER PRIMARY KEY, customer_name TEXT)")
        )
        connection.execute(sa.text("CREATE VIEW eu_orders AS SELECT * FROM orders"))
    yield engine
    forget(engine)
    engine.dispose()


@pytest.fixture()
def schema(engine):
    loaded = snapshot(engine, refresh=True)
    for table in loaded.tables:
        load_columns(engine, table)
    return loaded


class TestSchemaSnapshot:
    def test_it_lists_tables_and_views_apart(self, schema) -> None:
        by_name = {table.name: table for table in schema.tables}
        assert by_name["orders"].kind == "table"
        assert by_name["eu_orders"].kind == "view"

    def test_columns_carry_type_nullability_and_key(self, engine) -> None:
        table = load_columns(engine, snapshot(engine, refresh=True).find("orders"))
        by_name = {column.name: column for column in table.columns}
        assert by_name["id"].primary_key
        assert not by_name["customer_id"].nullable
        assert by_name["region"].nullable
        assert "TEXT" in by_name["region"].type.upper()

    def test_a_second_read_is_served_from_cache(self, engine) -> None:
        first = snapshot(engine, refresh=True)
        assert snapshot(engine) is first

    def test_refresh_reflects_a_new_table(self, engine) -> None:
        assert snapshot(engine, refresh=True).find("later") is None
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE later (a int)"))
        # Without the refresh the cache would still be within its window.
        assert snapshot(engine, refresh=True).find("later") is not None

    def test_forget_drops_the_cache_after_ddl(self, engine) -> None:
        first = snapshot(engine, refresh=True)
        forget(engine)
        assert snapshot(engine) is not first

    def test_a_table_is_findable_by_bare_or_qualified_name(self, schema) -> None:
        assert schema.find("orders") is not None
        assert schema.find("ORDERS") is not None
        assert schema.find('"orders"') is not None

    def test_an_unreadable_connection_says_so(self) -> None:
        broken = sa.create_engine("sqlite:////nonexistent-directory/db.sqlite")
        with pytest.raises(BadRequestError, match="Could not read the schema"):
            snapshot(broken, refresh=True)


class TestCursorContext:
    def test_the_start_of_a_statement_wants_a_statement_keyword(self) -> None:
        assert read_cursor("").context is Context.START
        assert read_cursor("SEL").context is Context.START

    def test_after_from_it_wants_a_table(self) -> None:
        assert read_cursor("SELECT * FROM ").context is Context.TABLE
        assert read_cursor("SELECT * FROM ord").context is Context.TABLE
        assert read_cursor("SELECT * FROM a JOIN ").context is Context.TABLE

    def test_after_select_it_wants_a_column(self) -> None:
        assert read_cursor("SELECT ").context is Context.COLUMN
        assert read_cursor("SELECT a, ").context is Context.COLUMN
        assert read_cursor("SELECT * FROM t WHERE ").context is Context.COLUMN

    def test_a_dot_means_that_table_and_nothing_else(self) -> None:
        cursor = read_cursor("SELECT o.")
        assert cursor.context is Context.QUALIFIED_COLUMN
        assert cursor.qualifier == "o"
        assert cursor.prefix == ""

    def test_it_reads_the_partial_word(self) -> None:
        assert read_cursor("SELECT * FROM cust").prefix == "cust"
        assert read_cursor("SELECT o.reg").prefix == "reg"

    def test_only_the_statement_under_the_cursor_counts(self) -> None:
        # The previous statement's FROM must not decide this one's context.
        assert read_cursor("SELECT * FROM orders; SEL").context is Context.START

    def test_a_keyword_inside_a_comment_does_not_change_context(self) -> None:
        assert read_cursor("SELECT * -- FROM x\n, ").context is Context.COLUMN

    def test_a_keyword_inside_a_literal_does_not_either(self) -> None:
        assert read_cursor("SELECT 'from nowhere', ").context is Context.COLUMN


class TestScope:
    def test_it_finds_a_plain_table(self) -> None:
        assert tables_in_scope("SELECT * FROM orders")["orders"] == "orders"

    def test_it_finds_an_alias(self) -> None:
        scope = tables_in_scope("SELECT * FROM orders o")
        assert scope["o"] == "orders"
        assert scope["orders"] == "orders"

    def test_it_finds_an_explicit_as_alias(self) -> None:
        assert tables_in_scope("SELECT * FROM orders AS o")["o"] == "orders"

    def test_it_finds_both_sides_of_a_join(self) -> None:
        scope = tables_in_scope("SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id")
        assert scope["o"] == "orders"
        assert scope["c"] == "customers"

    def test_a_following_keyword_is_not_mistaken_for_an_alias(self) -> None:
        scope = tables_in_scope("SELECT * FROM orders WHERE id = 1")
        assert "where" not in scope
        assert scope["orders"] == "orders"

    def test_a_qualified_table_is_reachable_by_its_bare_name(self) -> None:
        scope = tables_in_scope("SELECT * FROM public.orders")
        assert scope["orders"] == "public.orders"


class TestCompletions:
    def labels(self, schema, sql, offset=None):
        return [entry.label for entry in complete(schema, sql, offset)]

    def test_after_from_it_offers_tables_and_not_columns(self, schema) -> None:
        labels = self.labels(schema, "SELECT * FROM ")
        assert "orders" in labels
        assert "customers" in labels
        assert "region" not in labels

    def test_a_prefix_narrows_and_ranks(self, schema) -> None:
        labels = self.labels(schema, "SELECT * FROM cust")
        assert labels[0] == "customers"

    def test_a_dot_offers_only_that_table_s_columns(self, schema) -> None:
        labels = self.labels(schema, "SELECT o. FROM orders o", offset=len("SELECT o."))
        assert set(labels) == {"id", "customer_id", "region", "amount"}
        assert "customer_name" not in labels

    def test_columns_come_from_the_tables_actually_joined(self, schema) -> None:
        sql = "SELECT  FROM orders o JOIN customers c ON o.customer_id = c.id"
        labels = self.labels(schema, sql, offset=len("SELECT "))
        assert "region" in labels
        assert "customer_name" in labels

    def test_a_column_shows_its_table_and_type(self, schema) -> None:
        entries = complete(schema, "SELECT o.reg FROM orders o", offset=len("SELECT o.reg"))
        assert entries[0].label == "region"
        assert "orders" in entries[0].detail

    def test_a_key_column_says_so(self, schema) -> None:
        entries = {e.label: e for e in complete(schema, "SELECT o.", offset=9)}
        # No FROM yet, so nothing is in scope and tables are offered instead.
        entries = {e.label: e for e in complete(schema, "SELECT o. FROM orders o", offset=9)}
        assert "key" in entries["id"].detail
        assert "required" in entries["customer_id"].detail

    def test_a_subsequence_finds_a_long_name(self, schema) -> None:
        # Typing three letters instead of twelve is the point.
        labels = self.labels(schema, "SELECT cn FROM customers", offset=len("SELECT cn"))
        assert "customer_name" in labels

    def test_the_start_of_a_statement_offers_statement_keywords(self, schema) -> None:
        labels = self.labels(schema, "")
        assert "SELECT" in labels
        assert "orders" not in labels

    def test_an_unknown_qualifier_falls_back_to_tables(self, schema) -> None:
        # `zzz.` names nothing; offering that table's columns is impossible, so
        # offer what could be meant instead of nothing at all.
        labels = self.labels(schema, "SELECT zzz. FROM orders", offset=len("SELECT zzz."))
        assert "orders" in labels

    def test_the_limit_is_honoured(self, schema) -> None:
        assert len(complete(schema, "SELECT * FROM t WHERE ", limit=5)) == 5

    def test_views_are_offered_and_labelled(self, schema) -> None:
        entries = {e.label: e for e in complete(schema, "SELECT * FROM eu")}
        assert entries["eu_orders"].kind == "view"


class TestTheCacheIsKeyedSafely:
    def test_two_engines_do_not_share_a_snapshot(self) -> None:
        """`id(engine)` would be simpler and wrong twice over.

        The entry outlives the engine, and CPython reuses ids -- so a new engine
        can inherit a dead one's cached schema and autocomplete against the
        wrong database.
        """
        first = sa.create_engine("sqlite://")
        second = sa.create_engine("sqlite://")
        with first.begin() as connection:
            connection.execute(sa.text("CREATE TABLE only_in_first (a int)"))
        with second.begin() as connection:
            connection.execute(sa.text("CREATE TABLE only_in_second (a int)"))

        assert snapshot(first).find("only_in_first") is not None
        assert snapshot(second).find("only_in_first") is None
        assert snapshot(second).find("only_in_second") is not None
        first.dispose()
        second.dispose()

    def test_a_disposed_engine_does_not_keep_its_snapshot_alive(self) -> None:
        import gc

        from service_workbench.schema_tree import _CACHE

        engine = sa.create_engine("sqlite://")
        snapshot(engine, refresh=True)
        assert len(_CACHE) >= 1
        before = len(_CACHE)
        engine.dispose()
        del engine
        gc.collect()
        assert len(_CACHE) < before or before == 0
