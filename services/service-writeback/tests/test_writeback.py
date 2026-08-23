"""Compiling and applying a change set.

This is the code that writes to somebody's database, so the tests are weighted
towards the ways it could go wrong rather than the ways it works: a WHERE clause
that matches too much, a rehearsal that leaves traces, a concurrent edit that is
silently overwritten, a value that turns into syntax.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from shared_python.errors import BadRequestError, ConflictError
from service_writeback.compiler import Unsupported, compile_change_set
from service_writeback.edits import Edit, EditKind, row_version
from service_writeback.execute import (
    BlastRadius,
    commit,
    count_rows,
    dry_run,
    export_as_migration,
)
from service_writeback.identity import read_shape


@pytest.fixture()
def engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, amount REAL)")
        )
        connection.execute(
            sa.text(
                "INSERT INTO orders VALUES (1,'eu',10.0),(2,'us',20.0),"
                "(3,'eu',30.0),(4,NULL,40.0)"
            )
        )
        connection.execute(sa.text("CREATE TABLE keyless (a TEXT, b TEXT)"))
        connection.execute(sa.text("INSERT INTO keyless VALUES ('x','1'),('x','2')"))
    yield engine
    engine.dispose()


def shape_of(engine, table="orders", **kwargs):
    return read_shape(engine, table=table, **kwargs)


def rows(engine, sql="SELECT id, region, amount FROM orders ORDER BY id"):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(sa.text(sql))]


class TestRefusals:
    """The cases that must not compile at all."""

    def test_editing_a_keyless_table_is_refused(self, engine) -> None:
        shape = shape_of(engine, "keyless")
        edit = Edit(EditKind.SET_CELL, key={"a": "x"}, column="b", value="9")
        with pytest.raises(BadRequestError, match="no way to say which row"):
            compile_change_set(engine, shape, [edit])

    def test_editing_the_key_column_is_refused(self, engine) -> None:
        # Changing a key is a delete plus an insert -- a different decision with
        # different consequences, not a cell edit.
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="id", value=99)
        with pytest.raises(BadRequestError, match="identifies the row"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_an_edit_without_key_values_is_refused(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={}, column="region", value="x")
        with pytest.raises(BadRequestError, match="missing key value"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_an_unknown_column_is_refused(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="ghost", value="x")
        with pytest.raises(BadRequestError, match="not in this table"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_dropping_the_key_column_is_refused(self, engine) -> None:
        edit = Edit(EditKind.DROP_COLUMN, column="id")
        with pytest.raises(BadRequestError, match="no way to address"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_an_unapproved_column_type_is_refused(self, engine) -> None:
        # The type is interpolated into DDL and cannot be a bound parameter, so
        # it is checked against an allowlist rather than escaped.
        edit = Edit(EditKind.ADD_COLUMN, column="x", column_type="text; DROP TABLE orders")
        with pytest.raises(BadRequestError, match="not a column type"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_a_non_numeric_size_is_refused(self, engine) -> None:
        edit = Edit(EditKind.ADD_COLUMN, column="x", column_type="varchar(abc)")
        with pytest.raises(BadRequestError, match="not a number"):
            compile_change_set(engine, shape_of(engine), [edit])

    def test_renaming_on_mysql_refuses_rather_than_retyping(self) -> None:
        # MySQL's CHANGE needs the full column definition; emitting a rename
        # without it would silently alter the column's type.
        engine = sa.create_engine("mysql+pymysql://u:p@localhost/db")
        from service_writeback.identity import IdentityKind, RowIdentity, TableShape

        fake = TableShape(
            table="t", schema=None, columns=("id", "a"), nullable=frozenset(),
            identity=RowIdentity(IdentityKind.PRIMARY_KEY, ("id",)),
        )
        with pytest.raises(Unsupported, match="restating its full definition"):
            compile_change_set(engine, fake, [Edit(EditKind.RENAME_COLUMN, column="a", new_name="b")])


class TestStatementSafety:
    def test_values_are_bound_never_interpolated(self, engine) -> None:
        # A value containing a quote must be data, not syntax.
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="O'Brien")
        compiled = compile_change_set(engine, shape_of(engine), [edit])
        assert "O'Brien" not in compiled.statements[0].sql
        assert "O'Brien" in compiled.statements[0].params.values()

    def test_a_quote_in_a_value_survives_a_round_trip(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="O'Brien")
        commit(engine, compile_change_set(engine, shape_of(engine), [edit]))
        assert rows(engine)[0][1] == "O'Brien"

    def test_every_update_is_addressed_by_the_key(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x")
        sql = compile_change_set(engine, shape_of(engine), [edit]).statements[0].sql
        assert "WHERE" in sql and "id" in sql

    def test_edits_to_one_row_become_a_single_update(self, engine) -> None:
        edits = [
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
            Edit(EditKind.SET_CELL, key={"id": 1}, column="amount", value=1.0),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        assert len(compiled.statements) == 1

    def test_two_edits_to_the_same_cell_keep_the_last(self, engine) -> None:
        # It is what the person is looking at on screen.
        edits = [
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="first"),
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="second"),
        ]
        commit(engine, compile_change_set(engine, shape_of(engine), edits))
        assert rows(engine)[0][1] == "second"


class TestOrdering:
    def test_structure_changes_run_before_data(self, engine) -> None:
        edits = [
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
            Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        assert compiled.statements[0].is_ddl

    def test_deletes_run_after_updates(self, engine) -> None:
        # An update against a row deleted earlier would silently affect nothing,
        # and the dry run would report a count nobody could explain.
        edits = [
            Edit(EditKind.DELETE_ROW, key={"id": 2}),
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        assert "DELETE" in compiled.statements[-1].sql

    def test_a_dropped_column_is_dropped_last(self, engine) -> None:
        edits = [
            Edit(EditKind.DROP_COLUMN, column="amount"),
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        assert "DROP COLUMN" in compiled.statements[-1].sql


class TestDryRunLeavesNoTrace:
    def test_it_reports_real_counts_not_estimates(self, engine) -> None:
        edits = [
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
            Edit(EditKind.DELETE_ROW, key={"id": 2}),
        ]
        result = dry_run(engine, compile_change_set(engine, shape_of(engine), edits))
        assert result.rows_affected == 2

    def test_the_table_is_untouched_afterwards(self, engine) -> None:
        before = rows(engine)
        edits = [Edit(EditKind.DELETE_ROW, key={"id": 2})]
        dry_run(engine, compile_change_set(engine, shape_of(engine), edits))
        assert rows(engine) == before

    def test_it_notices_a_statement_that_would_hit_nothing(self, engine) -> None:
        # The important case: the row is gone, or somebody changed it.
        edit = Edit(EditKind.SET_CELL, key={"id": 999}, column="region", value="x")
        result = dry_run(engine, compile_change_set(engine, shape_of(engine), [edit]))
        assert not result.clean
        assert result.conflicts[0].rows_affected == 0

    def test_it_rolls_back_even_when_a_statement_fails(self, engine) -> None:
        before = rows(engine)
        edits = [
            Edit(EditKind.DELETE_ROW, key={"id": 1}),
            Edit(EditKind.INSERT_ROW, values={"id": 3, "region": "dup", "amount": 1.0}),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        with pytest.raises(Exception):
            dry_run(engine, compiled)
        assert rows(engine) == before


class TestConcurrency:
    def test_a_concurrent_change_is_detected_and_nothing_is_written(self, engine) -> None:
        edit = Edit(
            EditKind.SET_CELL, key={"id": 1}, column="region", value="mine", previous="eu"
        )
        compiled = compile_change_set(engine, shape_of(engine), [edit])

        # Somebody else edits the same cell between the read and the commit.
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE orders SET region='theirs' WHERE id=1"))

        with pytest.raises(ConflictError, match="Somebody else has changed"):
            commit(engine, compiled)
        assert rows(engine)[0][1] == "theirs", "the other person's value must survive"

    def test_a_previously_null_cell_is_still_checked(self, engine) -> None:
        # `x = NULL` is never true, so a naive check would make every update to
        # a null cell silently affect nothing.
        edit = Edit(
            EditKind.SET_CELL, key={"id": 4}, column="region", value="filled", previous=None
        )
        result = commit(engine, compile_change_set(engine, shape_of(engine), [edit]))
        assert result.committed
        assert rows(engine)[3][1] == "filled"

    def test_an_edit_that_recorded_nothing_gets_no_check(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x")
        sql = compile_change_set(engine, shape_of(engine), [edit]).statements[0].sql
        assert "OR (" not in sql

    def test_conflicts_can_be_accepted_deliberately(self, engine) -> None:
        edit = Edit(EditKind.SET_CELL, key={"id": 999}, column="region", value="x")
        compiled = compile_change_set(engine, shape_of(engine), [edit])
        result = commit(engine, compiled, allow_conflicts=True)
        assert result.committed
        assert not result.clean

    def test_a_row_fingerprint_distinguishes_null_from_the_word(self, engine) -> None:
        assert row_version({"a": None}, ("a",)) != row_version({"a": "None"}, ("a",))

    def test_a_row_fingerprint_changes_when_any_column_changes(self, engine) -> None:
        columns = ("a", "b")
        before = row_version({"a": "1", "b": "2"}, columns)
        assert before != row_version({"a": "1", "b": "3"}, columns)


class TestBlastRadius:
    def test_a_small_change_needs_no_confirmation(self) -> None:
        assert not BlastRadius(rows_affected=5, table_rows=10_000).needs_confirmation

    def test_a_large_absolute_change_does(self) -> None:
        assert BlastRadius(rows_affected=5_000, table_rows=10_000_000).needs_confirmation

    def test_a_large_proportional_change_does_even_when_small(self) -> None:
        # Thirty rows is nothing until the table has sixty.
        assert BlastRadius(rows_affected=30, table_rows=60).needs_confirmation

    def test_a_share_of_a_tiny_table_is_not_a_risk_signal(self) -> None:
        """One row of three is 33% of the table and still one row.

        Asking for the table name here would teach people to type it without
        reading, which is exactly what the prompt exists to prevent.
        """
        assert not BlastRadius(rows_affected=1, table_rows=3).needs_confirmation
        assert not BlastRadius(rows_affected=3, table_rows=3).needs_confirmation
        assert not BlastRadius(rows_affected=24, table_rows=25).needs_confirmation

    def test_it_explains_itself_in_both_cases(self) -> None:
        assert "Confirm" in BlastRadius(30, 60).explain()
        assert "Confirm" not in BlastRadius(1, 10_000).explain()

    def test_an_empty_table_does_not_divide_by_zero(self) -> None:
        assert BlastRadius(0, 0).share == 0.0


class TestCommit:
    def test_it_applies_everything(self, engine) -> None:
        edits = [
            Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="EMEA"),
            Edit(EditKind.INSERT_ROW, values={"id": 9, "region": "new", "amount": 1.0}),
            Edit(EditKind.DELETE_ROW, key={"id": 2}),
        ]
        result = commit(engine, compile_change_set(engine, shape_of(engine), edits))
        assert result.committed
        assert count_rows(engine, shape_of(engine)) == 4
        assert "note" in shape_of(engine).columns

    def test_a_failure_leaves_nothing_behind(self, engine) -> None:
        before = rows(engine)
        edits = [
            Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="ok"),
            Edit(EditKind.INSERT_ROW, values={"id": 3, "region": "dup", "amount": 1.0}),
        ]
        compiled = compile_change_set(engine, shape_of(engine), edits)
        with pytest.raises(BadRequestError):
            commit(engine, compiled)
        assert rows(engine) == before, "the earlier update must not survive"

    def test_irreversible_statements_are_flagged(self, engine) -> None:
        compiled = compile_change_set(
            engine, shape_of(engine), [Edit(EditKind.DELETE_ROW, key={"id": 1})]
        )
        assert compiled.has_irreversible


class TestMigrationExport:
    def test_it_renders_runnable_sql(self, engine) -> None:
        edits = [Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="EMEA")]
        text_out = export_as_migration(
            compile_change_set(engine, shape_of(engine), edits), title="demo"
        )
        assert "BEGIN;" in text_out and "COMMIT;" in text_out
        assert ":u0_v0" not in text_out, "parameters must be inlined for a file"

    def test_it_escapes_quotes_in_values(self, engine) -> None:
        edits = [Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="O'Brien")]
        text_out = export_as_migration(
            compile_change_set(engine, shape_of(engine), edits), title="demo"
        )
        assert "O''Brien" in text_out

    def test_longer_parameter_names_are_substituted_first(self, engine) -> None:
        # `:u0_k1` must not partly replace `:u0_k10`.
        edits = [
            Edit(EditKind.SET_CELL, key={"id": index}, column="region", value=f"v{index}")
            for index in range(1, 13)
        ]
        text_out = export_as_migration(
            compile_change_set(engine, shape_of(engine), edits), title="demo"
        )
        assert ":u1" not in text_out and ":u10" not in text_out


class TestRehearsalLeavesNothingBehind:
    """The rehearsal must not be the change, on any dialect.

    This is a bug class, not a bug: pysqlite commits DDL outside the
    transaction, so an `ALTER TABLE` in a dry run used to survive the rollback
    and the second attempt then failed with "duplicate column name".
    """

    def test_a_rehearsed_column_is_not_actually_added(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.ADD_COLUMN, column="note", column_type="text")],
        )
        dry_run(engine, compiled)
        assert "note" not in shape_of(engine).columns
        # And the same plan still applies cleanly afterwards.
        commit(engine, compiled)
        assert "note" in shape_of(engine).columns

    def test_a_rehearsed_column_is_not_actually_dropped(self, engine) -> None:
        compiled = compile_change_set(
            engine, shape_of(engine), [Edit(EditKind.DROP_COLUMN, column="region")]
        )
        dry_run(engine, compiled)
        assert "region" in shape_of(engine).columns

    def test_rows_are_untouched_by_a_rehearsal(self, engine) -> None:
        before = rows(engine)
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="zz"),
                Edit(EditKind.DELETE_ROW, key={"id": 2}),
                Edit(EditKind.INSERT_ROW, values={"id": 99, "region": "n", "amount": 1.0}),
            ],
        )
        dry_run(engine, compiled)
        assert rows(engine) == before

    def test_a_statement_needing_unrehearsed_structure_is_explained(self, engine) -> None:
        """Adding a column and filling it in the same change set.

        The UPDATE cannot run in the rehearsal because the column is not there
        yet, and the driver error for that is an artefact of rehearsing, not a
        problem with the change.
        """
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
                Edit(EditKind.SET_CELL, key={"id": 1}, column="note", value="hello"),
            ],
        )
        result = dry_run(engine, compiled)
        assert any("could not be rehearsed" in warning for warning in result.warnings)
        # Every statement still has a slot, in plan order.
        assert len(result.outcomes) == len(compiled.statements)
        assert all("not rehearsed" in outcome.describes for outcome in result.outcomes)
        assert rows(engine) == rows(engine)
        commit(engine, compiled)
        with engine.connect() as connection:
            assert (
                connection.execute(sa.text("SELECT note FROM orders WHERE id = 1")).scalar_one()
                == "hello"
            )


class TestChangeSetWideValidation:
    """A change set is validated as a whole, not edit by edit.

    "Add a column, then type values into it" is the commonest thing anyone will
    do in the Studio, and checking each edit against today's table makes it
    impossible.
    """

    def test_a_column_can_be_added_and_filled_in_one_change_set(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
                Edit(EditKind.SET_CELL, key={"id": 1}, column="note", value="hello"),
            ],
        )
        # Structure first, so the UPDATE has somewhere to write.
        assert compiled.statements[0].is_ddl
        commit(engine, compiled)
        with engine.connect() as connection:
            assert (
                connection.execute(sa.text("SELECT note FROM orders WHERE id = 1")).scalar_one()
                == "hello"
            )

    def test_a_column_can_be_written_then_dropped(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="zz"),
                Edit(EditKind.DROP_COLUMN, column="region"),
            ],
        )
        commit(engine, compiled)
        assert "region" not in shape_of(engine).columns

    def test_adding_the_same_column_twice_is_still_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="already exists"):
            compile_change_set(
                engine,
                shape_of(engine),
                [
                    Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
                    Edit(EditKind.ADD_COLUMN, column="note", column_type="text"),
                ],
            )

    def test_writing_to_a_column_nothing_creates_is_still_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="not in this table"):
            compile_change_set(
                engine,
                shape_of(engine),
                [Edit(EditKind.SET_CELL, key={"id": 1}, column="ghost", value=1)],
            )

    def test_a_renamed_column_can_be_written_under_its_new_name(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.RENAME_COLUMN, column="region", new_name="area"),
                Edit(EditKind.SET_CELL, key={"id": 1}, column="area", value="emea"),
            ],
        )
        commit(engine, compiled)
        with engine.connect() as connection:
            assert (
                connection.execute(sa.text("SELECT area FROM orders WHERE id = 1")).scalar_one()
                == "emea"
            )

    def test_renaming_the_key_alongside_row_edits_is_refused(self, engine) -> None:
        """Every other edit addresses rows by the old name."""
        with pytest.raises(BadRequestError, match="identifies rows"):
            compile_change_set(
                engine,
                shape_of(engine),
                [
                    Edit(EditKind.RENAME_COLUMN, column="id", new_name="order_id"),
                    Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="x"),
                ],
            )

    def test_renaming_the_key_on_its_own_is_allowed(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.RENAME_COLUMN, column="id", new_name="order_id")],
        )
        commit(engine, compiled)
        assert "order_id" in shape_of(engine).columns


class TestProjectColumns:
    def test_it_follows_compiler_order_not_staging_order(self) -> None:
        from service_writeback.edits import project_columns

        columns = ("a", "b")
        edits = [
            Edit(EditKind.DROP_COLUMN, column="b"),
            Edit(EditKind.ADD_COLUMN, column="c", column_type="text"),
            Edit(EditKind.RENAME_COLUMN, column="a", new_name="z"),
        ]
        assert project_columns(columns, edits) == ("z", "c")
        # Row edits run before the drops, so "b" is still addressable.
        assert project_columns(columns, edits, apply_drops=False) == ("z", "b", "c")


class TestHostileIdentifiers:
    """Identifiers are interpolated into DDL; values never are.

    A column called `x"); DROP TABLE orders; --` is a legal identifier in
    PostgreSQL. It has to come back out as an identifier, not as syntax.
    """

    def test_a_column_name_containing_a_quote_is_still_just_a_name(self, engine) -> None:
        hostile = 'note"); DROP TABLE orders; --'
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.ADD_COLUMN, column=hostile, column_type="text")],
        )
        commit(engine, compiled)
        assert hostile in shape_of(engine).columns
        # The table it tried to drop is still there, with its rows.
        assert count_rows(engine, shape_of(engine)) == 4

    def test_a_type_that_is_not_a_type_is_refused(self, engine) -> None:
        for hostile in ("text); DROP TABLE orders; --", "integer DEFAULT (SELECT 1)", "blob"):
            with pytest.raises(BadRequestError):
                compile_change_set(
                    engine,
                    shape_of(engine),
                    [Edit(EditKind.ADD_COLUMN, column="c", column_type=hostile)],
                )

    def test_a_size_that_is_not_a_number_is_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="size"):
            compile_change_set(
                engine,
                shape_of(engine),
                [Edit(EditKind.ADD_COLUMN, column="c", column_type="varchar(1); DROP TABLE t)")],
            )

    def test_a_size_is_kept(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.ADD_COLUMN, column="code", column_type="varchar(12)")],
        )
        assert "VARCHAR(12)" in compiled.statements[0].sql


class TestNoOpEdits:
    """An edit that writes what is already there is not a change.

    Dropping these is also what keeps MySQL honest: it reports rows *changed*,
    not rows matched, so such an UPDATE returns zero and the concurrency check
    would read that as somebody else having edited the row.
    """

    def test_writing_the_same_value_produces_no_statement(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(
                    EditKind.SET_CELL,
                    key={"id": 1},
                    column="region",
                    value="eu",
                    previous="eu",
                ),
                Edit(
                    EditKind.SET_CELL,
                    key={"id": 1},
                    column="amount",
                    value=99.0,
                    previous=10.0,
                ),
            ],
        )
        assert len(compiled.statements) == 1
        assert "amount" in compiled.statements[0].sql
        assert "region" not in compiled.statements[0].sql

    def test_a_change_set_of_only_no_ops_is_refused(self, engine) -> None:
        with pytest.raises(BadRequestError, match="already holds"):
            compile_change_set(
                engine,
                shape_of(engine),
                [
                    Edit(
                        EditKind.SET_CELL,
                        key={"id": 1},
                        column="region",
                        value="eu",
                        previous="eu",
                    )
                ],
            )

    def test_it_looks_past_the_string_number_divide(self, engine) -> None:
        """A grid hands back "10.0" for a cell that came out as 10.0."""
        with pytest.raises(BadRequestError, match="already holds"):
            compile_change_set(
                engine,
                shape_of(engine),
                [
                    Edit(
                        EditKind.SET_CELL,
                        key={"id": 1},
                        column="amount",
                        value="10.0",
                        previous=10.0,
                    )
                ],
            )

    def test_null_and_empty_string_are_not_the_same(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.SET_CELL, key={"id": 4}, column="region", value="", previous=None)],
        )
        assert len(compiled.statements) == 1

    def test_an_edit_that_recorded_nothing_is_always_written(self, engine) -> None:
        """Unchanged is a claim, and nobody made it here."""
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="eu")],
        )
        assert len(compiled.statements) == 1


class TestBatching:
    """Rows that update the same columns become one statement, not one each."""

    def test_rows_with_the_same_shape_share_a_statement(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="a"),
                Edit(EditKind.SET_CELL, key={"id": 2}, column="region", value="b"),
                Edit(EditKind.SET_CELL, key={"id": 3}, column="region", value="c"),
            ],
        )
        assert len(compiled.statements) == 1
        assert compiled.statements[0].expected_rows == 3
        assert len(compiled.statements[0].param_sets or []) == 3
        commit(engine, compiled)
        assert [row[1] for row in rows(engine)][:3] == ["a", "b", "c"]

    def test_rows_setting_different_columns_stay_apart(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="a"),
                Edit(EditKind.SET_CELL, key={"id": 2}, column="amount", value=1.0),
            ],
        )
        assert len(compiled.statements) == 2

    def test_a_checked_row_does_not_batch_with_an_unchecked_one(self, engine) -> None:
        """Their WHERE clauses are different, so their SQL has to be too."""
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="a", previous="eu"),
                Edit(EditKind.SET_CELL, key={"id": 2}, column="region", value="b"),
            ],
        )
        assert len(compiled.statements) == 2

    def test_one_stale_row_in_a_batch_stops_the_whole_commit(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="a", previous="eu"),
                Edit(EditKind.SET_CELL, key={"id": 2}, column="region", value="b", previous="STALE"),
            ],
        )
        assert len(compiled.statements) == 1
        with pytest.raises(ConflictError):
            commit(engine, compiled)
        # Nothing was written, including the row that would have succeeded.
        assert [row[1] for row in rows(engine)][:2] == ["eu", "us"]

    def test_the_migration_writes_one_statement_per_row(self, engine) -> None:
        compiled = compile_change_set(
            engine,
            shape_of(engine),
            [
                Edit(EditKind.SET_CELL, key={"id": 1}, column="region", value="a"),
                Edit(EditKind.SET_CELL, key={"id": 2}, column="region", value="b"),
            ],
        )
        sql = export_as_migration(compiled, title="t")
        # A bind marker left in a migration file is not a migration.
        assert ":u0_" not in sql
        assert sql.count("UPDATE") == 2
        assert "'a'" in sql and "'b'" in sql
