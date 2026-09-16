"""Running scripts against a real database.

SQLite here, as everywhere else in this repository: it is the one engine
available on this machine, and a test that mocks the driver would only prove the
mock agrees with itself.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from shared_python.errors import BadRequestError, ForbiddenError
from service_workbench.execute import MAX_ROW_LIMIT, explain, run_script
from service_workbench.safety import SessionPolicy


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
    yield engine
    engine.dispose()


WRITEABLE = SessionPolicy(allow_writes=True)
STRUCTURAL = SessionPolicy(allow_writes=True, allow_ddl=True)


def rows_of(engine, sql="SELECT id, region FROM orders ORDER BY id"):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(sa.text(sql))]


class TestReading:
    def test_it_returns_columns_and_rows(self, engine) -> None:
        result = run_script(engine, "SELECT id, region FROM orders ORDER BY id")
        first = result.statements[0]
        assert first.columns == ["id", "region"]
        assert first.rows[0] == {"id": 1, "region": "eu"}
        assert first.row_count == 4
        assert not result.failed

    def test_every_statement_gets_its_own_result(self, engine) -> None:
        result = run_script(engine, "SELECT 1 AS a; SELECT 2 AS b; SELECT 3 AS c")
        assert [s.index for s in result.statements] == [1, 2, 3]
        assert [s.columns for s in result.statements] == [["a"], ["b"], ["c"]]

    def test_each_statement_is_timed(self, engine) -> None:
        result = run_script(engine, "SELECT 1; SELECT 2")
        assert all(s.duration_ms >= 0 for s in result.statements)
        assert result.duration_ms >= 0

    def test_null_survives_as_null_not_as_the_string_none(self, engine) -> None:
        result = run_script(engine, "SELECT region FROM orders WHERE id = 4")
        assert result.statements[0].rows == [{"region": None}]

    def test_results_are_capped_and_say_so(self, engine) -> None:
        result = run_script(
            engine, "SELECT * FROM orders", policy=SessionPolicy(row_limit=2)
        )
        first = result.statements[0]
        assert first.row_count == 2
        assert first.truncated is True

    def test_a_result_that_fits_is_not_marked_truncated(self, engine) -> None:
        result = run_script(engine, "SELECT * FROM orders", policy=SessionPolicy(row_limit=4))
        assert result.statements[0].truncated is False

    def test_the_hard_cap_beats_a_generous_policy(self, engine) -> None:
        # A policy cannot ask for a million rows in memory.
        result = run_script(
            engine, "SELECT * FROM orders", policy=SessionPolicy(row_limit=10_000_000)
        )
        assert result.statements[0].row_count <= MAX_ROW_LIMIT


class TestErrors:
    def test_a_bad_statement_reports_the_database_message(self, engine) -> None:
        result = run_script(engine, "SELECT * FROM nope")
        assert result.failed
        assert "nope" in result.statements[0].error

    def test_the_message_is_not_wrapped_in_sqlalchemy_noise(self, engine) -> None:
        error = run_script(engine, "SELECT * FROM nope").statements[0].error
        assert "[SQL:" not in error
        assert "Background on this error" not in error

    def test_later_statements_are_reported_as_skipped_not_missing(self, engine) -> None:
        result = run_script(engine, "SELECT 1; SELECT * FROM nope; SELECT 3")
        assert [s.index for s in result.statements] == [1, 2, 3]
        assert result.statements[0].succeeded
        assert result.statements[1].error
        assert result.statements[2].skipped

    def test_a_failed_statement_is_still_timed(self, engine) -> None:
        assert run_script(engine, "SELECT * FROM nope").statements[0].duration_ms >= 0

    def test_first_error_names_the_statement(self, engine) -> None:
        result = run_script(engine, "SELECT 1; SELECT * FROM nope")
        assert result.first_error.startswith("Statement 2:")


class TestWrites:
    def test_a_write_is_refused_in_a_read_only_session(self, engine) -> None:
        with pytest.raises(ForbiddenError, match="read-only"):
            run_script(engine, "DELETE FROM orders")
        assert len(rows_of(engine)) == 4

    def test_a_write_runs_when_the_session_allows_it(self, engine) -> None:
        result = run_script(
            engine, "UPDATE orders SET region = 'emea' WHERE id = 1", policy=WRITEABLE
        )
        assert result.statements[0].rows_affected == 1
        assert result.committed
        assert rows_of(engine)[0] == (1, "emea")

    def test_ddl_needs_its_own_permission_on_top(self, engine) -> None:
        with pytest.raises(ForbiddenError, match="structure"):
            run_script(engine, "DROP TABLE orders", policy=WRITEABLE)
        assert rows_of(engine)

    def test_ddl_runs_when_structure_changes_are_enabled(self, engine) -> None:
        result = run_script(engine, "CREATE TABLE t2 (a int)", policy=STRUCTURAL)
        assert not result.failed
        assert "t2" in sa.inspect(engine).get_table_names()

    def test_a_whole_script_rolls_back_when_one_statement_fails(self, engine) -> None:
        # Half-applied is worse than not applied: nobody knows which half.
        result = run_script(
            engine,
            "UPDATE orders SET region = 'zz' WHERE id = 1; UPDATE nope SET a = 1",
            policy=WRITEABLE,
        )
        assert result.failed
        assert not result.committed
        assert rows_of(engine)[0] == (1, "eu")

    def test_a_data_modifying_cte_is_refused_in_a_read_only_session(self, engine) -> None:
        with pytest.raises(ForbiddenError):
            run_script(
                engine,
                "WITH gone AS (DELETE FROM orders WHERE id = 1 RETURNING *) SELECT * FROM gone",
            )
        assert len(rows_of(engine)) == 4


class TestParameters:
    def test_a_parameter_is_bound_not_interpolated(self, engine) -> None:
        result = run_script(
            engine,
            "SELECT id FROM orders WHERE region = :region",
            parameters={"region": "eu"},
        )
        assert [row["id"] for row in result.statements[0].rows] == [1, 3]

    def test_a_parameter_value_cannot_smuggle_sql(self, engine) -> None:
        result = run_script(
            engine,
            "SELECT id FROM orders WHERE region = :region",
            parameters={"region": "eu'; DROP TABLE orders; --"},
        )
        assert result.statements[0].rows == []
        assert "orders" in sa.inspect(engine).get_table_names()

    def test_a_missing_parameter_is_named(self, engine) -> None:
        with pytest.raises(BadRequestError, match="region"):
            run_script(engine, "SELECT * FROM orders WHERE region = :region")

    def test_an_explicit_null_parameter_is_not_missing(self, engine) -> None:
        result = run_script(
            engine,
            "SELECT id FROM orders WHERE region IS :region",
            parameters={"region": None},
        )
        assert [row["id"] for row in result.statements[0].rows] == [4]


class TestExplain:
    def test_it_returns_a_plan_without_running_the_query(self, engine) -> None:
        plan = explain(engine, "SELECT * FROM orders WHERE region = 'eu'")
        assert plan.dialect == "sqlite"
        assert plan.text
        assert plan.rows

    def test_it_notices_a_full_table_scan(self, engine) -> None:
        plan = explain(engine, "SELECT * FROM orders WHERE region = 'eu'")
        assert any("whole table" in note for note in plan.notes)

    def test_it_refuses_more_than_one_statement(self, engine) -> None:
        with pytest.raises(BadRequestError, match="single statement"):
            explain(engine, "SELECT 1; SELECT 2")

    def test_explaining_a_write_does_not_perform_it(self, engine) -> None:
        # EXPLAIN, never EXPLAIN ANALYZE: the point of asking for a plan is to
        # avoid running the thing.
        explain(engine, "DELETE FROM orders WHERE id = 1")
        assert len(rows_of(engine)) == 4


class TestValueRendering:
    def test_a_decimal_survives_as_text_rather_than_a_float(self, engine) -> None:
        from decimal import Decimal

        from service_workbench.execute import _json_safe

        # Rendering as a float loses the exactness the type was chosen for.
        assert _json_safe(Decimal("1.10")) == "1.10"

    def test_dates_and_uuids_become_strings(self) -> None:
        import datetime
        import uuid

        from service_workbench.execute import _json_safe

        assert _json_safe(datetime.date(2026, 8, 23)) == "2026-08-23"
        identifier = uuid.uuid4()
        assert _json_safe(identifier) == str(identifier)

    def test_bytes_are_described_rather_than_dumped(self) -> None:
        from service_workbench.execute import _json_safe

        assert _json_safe(b"\x00\x01\x02") == "<3 bytes>"

    def test_nan_and_infinity_become_null(self) -> None:
        from service_workbench.execute import _json_safe

        assert _json_safe(float("nan")) is None
        assert _json_safe(float("inf")) is None


class TestStatementTimeout:
    """A workbench without one is a way to take a database down.

    A runaway query holds a server-side connection for as long as the database
    will keep going, and closing the browser tab does not stop it.
    """

    def test_a_timeout_is_requested_on_every_run(self, monkeypatch) -> None:
        import sqlalchemy as sa_module

        from service_workbench import execute as module

        asked: list[str] = []
        real = module._apply_timeout

        def spy(connection, dialect, seconds):
            asked.append(f"{dialect}:{seconds}")
            return real(connection, dialect, seconds)

        monkeypatch.setattr(module, "_apply_timeout", spy)
        engine = sa_module.create_engine("sqlite://")
        run_script(engine, "SELECT 1", policy=SessionPolicy(timeout_seconds=7))
        assert asked == ["sqlite:7"]

    def test_postgres_is_told_in_milliseconds(self) -> None:
        from service_workbench.execute import _TIMEOUT_SQL

        assert _TIMEOUT_SQL["postgresql"].format(ms=30_000).endswith("= 30000")
        # SET LOCAL, so it applies to this transaction and no other.
        assert "LOCAL" in _TIMEOUT_SQL["postgresql"]

    def test_mysql_has_its_own_spelling(self) -> None:
        from service_workbench.execute import _TIMEOUT_SQL

        assert "max_execution_time" in _TIMEOUT_SQL["mysql"]

    def test_a_dialect_with_no_timeout_says_so_rather_than_staying_quiet(self) -> None:
        from service_workbench.execute import _apply_timeout

        note = _apply_timeout(None, "oracle", 30)
        assert note is not None
        assert "run to completion" in note

    def test_sqlite_is_a_known_absence_not_a_warning(self, engine) -> None:
        # It genuinely has no statement timeout; warning on every local run
        # would train people to ignore the warning that matters.
        result = run_script(engine, "SELECT 1")
        assert result.warnings == []
