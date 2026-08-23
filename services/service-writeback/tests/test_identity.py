"""How a row is identified.

This is the whole safety story of write-back: an UPDATE whose WHERE clause does
not identify exactly one row is a data-loss bug waiting for its moment. Every
branch of the preference order is pinned here, including the ones that refuse.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from shared_python.errors import BadRequestError
from service_writeback.identity import (
    IdentityKind,
    read_shape,
    resolve_identity,
    verify_designated_key,
)


@pytest.fixture()
def engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE with_pk (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(
            sa.text("CREATE TABLE composite_pk (a TEXT, b TEXT, v TEXT, PRIMARY KEY (a, b))")
        )
        connection.execute(
            sa.text("CREATE TABLE with_uq (code TEXT NOT NULL UNIQUE, name TEXT)")
        )
        connection.execute(sa.text("CREATE TABLE nullable_uq (code TEXT UNIQUE, name TEXT)"))
        connection.execute(sa.text("CREATE TABLE no_key (a TEXT, b TEXT)"))
        connection.execute(sa.text("INSERT INTO no_key VALUES ('x','1'),('x','2'),('y','3')"))
        connection.execute(sa.text("CREATE TABLE unique_values (k TEXT, v TEXT)"))
        connection.execute(sa.text("INSERT INTO unique_values VALUES ('a','1'),('b','2')"))
        connection.execute(sa.text("CREATE TABLE nullable_values (k TEXT, v TEXT)"))
        connection.execute(sa.text("INSERT INTO nullable_values VALUES ('a','1'),(NULL,'2')"))
    yield engine
    engine.dispose()


class TestPreferenceOrder:
    def test_a_primary_key_is_used(self, engine) -> None:
        identity = resolve_identity(engine, table="with_pk")
        assert identity.kind is IdentityKind.PRIMARY_KEY
        assert identity.columns == ("id",)
        assert identity.durable

    def test_a_composite_primary_key_keeps_every_column(self, engine) -> None:
        identity = resolve_identity(engine, table="composite_pk")
        assert set(identity.columns) == {"a", "b"}

    def test_a_not_null_unique_constraint_is_used_when_there_is_no_key(self, engine) -> None:
        identity = resolve_identity(engine, table="with_uq")
        assert identity.kind is IdentityKind.UNIQUE_CONSTRAINT
        assert identity.columns == ("code",)

    def test_a_nullable_unique_constraint_is_refused(self, engine) -> None:
        # SQL treats every NULL as distinct, so several rows may hold NULL there
        # and the "unique" column identifies none of them.
        identity = resolve_identity(engine, table="nullable_uq")
        assert identity.kind is IdentityKind.NONE

    def test_a_table_with_no_key_is_refused(self, engine) -> None:
        identity = resolve_identity(engine, table="no_key")
        assert not identity.usable

    def test_the_refusal_explains_what_to_do(self, engine) -> None:
        identity = resolve_identity(engine, table="no_key")
        assert "Add a primary key" in identity.reason

    def test_matching_on_all_columns_is_never_offered(self, engine) -> None:
        # There is deliberately no such fallback: it silently updates every
        # duplicate row.
        identity = resolve_identity(engine, table="no_key")
        assert identity.columns == ()


class TestPhysicalRowIdentity:
    def test_it_is_not_offered_unless_asked_for(self, engine) -> None:
        assert not resolve_identity(engine, table="no_key").usable

    def test_it_is_available_when_explicitly_allowed(self, engine) -> None:
        identity = resolve_identity(engine, table="no_key", allow_physical=True)
        assert identity.kind is IdentityKind.PHYSICAL
        assert identity.columns == ("rowid",)

    def test_it_is_marked_as_not_durable(self, engine) -> None:
        # It changes when the database reorganises the table, and an edit
        # written against a stale address hits the wrong row.
        identity = resolve_identity(engine, table="no_key", allow_physical=True)
        assert not identity.durable
        assert "VACUUM" in identity.caveat

    def test_the_refusal_mentions_it_as_an_option(self, engine) -> None:
        assert "rowid" in resolve_identity(engine, table="no_key").reason


class TestDesignatedKeys:
    def test_a_genuinely_unique_column_is_accepted(self, engine) -> None:
        identity = resolve_identity(engine, table="unique_values", designated=["k"])
        assert identity.kind is IdentityKind.DESIGNATED
        assert identity.columns == ("k",)

    def test_it_is_not_treated_as_durable(self, engine) -> None:
        # Nothing stops a duplicate being inserted later; it is a choice, not a
        # constraint, so it is re-checked before every commit.
        identity = resolve_identity(engine, table="unique_values", designated=["k"])
        assert not identity.durable
        assert identity.caveat

    def test_duplicates_are_refused_with_a_count(self, engine) -> None:
        with pytest.raises(BadRequestError, match="appear more than once"):
            resolve_identity(engine, table="no_key", designated=["a"])

    def test_nulls_are_refused_with_a_reason(self, engine) -> None:
        with pytest.raises(BadRequestError, match="every NULL as distinct"):
            resolve_identity(engine, table="nullable_values", designated=["k"])

    def test_an_unknown_column_is_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="not in"):
            resolve_identity(engine, table="unique_values", designated=["ghost"])

    def test_it_is_re_checked_and_not_trusted(self, engine) -> None:
        # A key that was unique an hour ago is not a constraint.
        verify_designated_key(engine, table="unique_values", schema=None, columns=["k"])
        with engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO unique_values VALUES ('a','3')"))
        with pytest.raises(BadRequestError, match="appear more than once"):
            verify_designated_key(engine, table="unique_values", schema=None, columns=["k"])

    def test_an_empty_key_is_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="at least one column"):
            verify_designated_key(engine, table="unique_values", schema=None, columns=[])


class TestTableShape:
    def test_it_reads_columns_and_nullability(self, engine) -> None:
        shape = read_shape(engine, table="with_pk")
        assert shape.columns == ("id", "name")
        assert "name" in shape.nullable

    def test_it_carries_the_identity(self, engine) -> None:
        assert read_shape(engine, table="with_pk").identity.kind is IdentityKind.PRIMARY_KEY

    def test_it_rejects_an_unknown_column(self, engine) -> None:
        shape = read_shape(engine, table="with_pk")
        with pytest.raises(BadRequestError, match="not in"):
            shape.require_columns(["ghost"])

    def test_a_missing_table_is_reported_clearly(self, engine) -> None:
        with pytest.raises(BadRequestError, match="does not exist"):
            read_shape(engine, table="not_a_table")


class TestRequire:
    def test_requiring_an_unusable_identity_raises_the_reason(self, engine) -> None:
        identity = resolve_identity(engine, table="no_key")
        with pytest.raises(BadRequestError, match="no way to say which row"):
            identity.require()

    def test_requiring_a_usable_identity_returns_the_columns(self, engine) -> None:
        assert resolve_identity(engine, table="with_pk").require() == ("id",)
