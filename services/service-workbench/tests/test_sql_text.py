"""Splitting and classifying SQL.

This is the module that decides whether a statement writes, so its failure mode
is not "a confusing error" -- it is somebody running a DELETE in what they were
told was a read-only session. The tests are weighted accordingly: most of them
are attempts to get a write past the classifier.
"""

from __future__ import annotations

import pytest

from shared_python.errors import BadRequestError
from service_workbench.sql_text import (
    MAX_STATEMENTS,
    Statement,
    StatementKind,
    classify,
    parameters_in,
    parse,
    split,
)


class TestSplitting:
    def test_it_splits_on_semicolons(self) -> None:
        pieces = split("SELECT 1; SELECT 2")
        assert [body.strip() for body, _, _ in pieces] == ["SELECT 1", "SELECT 2"]

    def test_a_trailing_semicolon_does_not_make_an_empty_statement(self) -> None:
        assert len(split("SELECT 1;")) == 1
        assert len(split("SELECT 1;\n\n  \n")) == 1

    def test_a_semicolon_inside_a_string_is_not_a_boundary(self) -> None:
        pieces = split("SELECT 'a;b' AS x; SELECT 2")
        assert len(pieces) == 2
        assert "'a;b'" in pieces[0][0]

    def test_a_doubled_quote_inside_a_string_is_a_quote(self) -> None:
        pieces = split("SELECT 'it''s; fine' AS x; SELECT 2")
        assert len(pieces) == 2

    def test_a_backslash_escaped_quote_is_handled(self) -> None:
        # MySQL honours these; a naive scanner ends the literal early and then
        # sees the rest of the string as code.
        pieces = split("SELECT 'a\\'; b' AS x; SELECT 2")
        assert len(pieces) == 2

    def test_a_semicolon_inside_a_quoted_identifier_is_not_a_boundary(self) -> None:
        assert len(split('SELECT "od;d" FROM t; SELECT 2')) == 2
        assert len(split("SELECT `od;d` FROM t; SELECT 2")) == 2

    def test_a_semicolon_inside_a_comment_is_not_a_boundary(self) -> None:
        assert len(split("SELECT 1 -- ; not a statement\n; SELECT 2")) == 2
        assert len(split("SELECT 1 /* ; nope */ ; SELECT 2")) == 2

    def test_a_dollar_quoted_body_survives_intact(self) -> None:
        # A function definition is full of semicolons and is one statement.
        script = """
        CREATE FUNCTION f() RETURNS int AS $$
        BEGIN
          PERFORM 1;
          RETURN 2;
        END;
        $$ LANGUAGE plpgsql;
        SELECT f()
        """
        pieces = split(script)
        assert len(pieces) == 2
        assert "RETURN 2;" in pieces[0][0]

    def test_a_tagged_dollar_quote_works_too(self) -> None:
        assert len(split("SELECT $tag$a;b$tag$; SELECT 2")) == 2

    def test_an_unterminated_literal_does_not_hang_or_split(self) -> None:
        # Malformed input must be handed to the database to complain about,
        # not silently cut in half.
        assert len(split("SELECT 'unterminated ; SELECT 2")) == 1

    def test_offsets_point_at_the_statement(self) -> None:
        script = "SELECT 1;\nSELECT 2"
        parsed = parse(script)
        second = parsed.statements[1]
        assert script[second.start : second.end].strip() == "SELECT 2"
        assert second.line == 2


class TestClassification:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "  select * from t  ",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "SHOW TABLES",
            "DESCRIBE t",
            "EXPLAIN SELECT 1",
            "VALUES (1)",
        ],
    )
    def test_reads_are_reads(self, sql: str) -> None:
        assert classify(sql) is StatementKind.READ

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET a = 1",
            "DELETE FROM t",
            "MERGE INTO t USING s ON 1=1",
            "TRUNCATE t",
            "COPY t FROM '/tmp/x'",
        ],
    )
    def test_writes_are_writes(self, sql: str) -> None:
        assert classify(sql) is StatementKind.WRITE
        assert classify(sql).writes

    @pytest.mark.parametrize(
        "sql", ["CREATE TABLE t (a int)", "ALTER TABLE t ADD b int", "DROP TABLE t", "GRANT ALL ON t TO x"]
    )
    def test_structure_changes_are_ddl(self, sql: str) -> None:
        assert classify(sql) is StatementKind.DDL
        assert classify(sql).writes

    def test_a_data_modifying_cte_is_a_write_despite_leading_with(self) -> None:
        # This is the one that gets past a leading-keyword check.
        sql = "WITH gone AS (DELETE FROM t WHERE a = 1 RETURNING *) SELECT * FROM gone"
        assert classify(sql) is StatementKind.WRITE

    def test_a_cte_that_creates_is_ddl(self) -> None:
        assert classify("WITH x AS (SELECT 1) CREATE TABLE y AS SELECT * FROM x") is StatementKind.DDL

    def test_explain_analyze_of_a_write_actually_writes(self) -> None:
        # EXPLAIN ANALYZE executes the statement. Treating it as a read would
        # run an INSERT in a read-only session.
        assert classify("EXPLAIN ANALYZE INSERT INTO t VALUES (1)") is StatementKind.WRITE

    def test_plain_explain_of_a_write_does_not(self) -> None:
        assert classify("EXPLAIN INSERT INTO t VALUES (1)") is StatementKind.READ

    def test_a_write_word_inside_a_string_does_not_make_a_read_a_write(self) -> None:
        assert classify("SELECT 'delete from t' AS note") is StatementKind.READ

    def test_a_write_word_inside_a_comment_does_not_either(self) -> None:
        assert classify("SELECT 1 -- delete from t\n") is StatementKind.READ

    def test_a_column_named_update_does_not_make_a_read_a_write(self) -> None:
        assert classify('SELECT "update" FROM t') is StatementKind.READ

    @pytest.mark.parametrize("sql", ["BEGIN", "COMMIT", "ROLLBACK", "SET search_path = x", "USE db"])
    def test_session_statements_are_their_own_kind(self, sql: str) -> None:
        assert classify(sql) is StatementKind.SESSION
        assert not classify(sql).writes

    def test_gibberish_is_unknown_rather_than_assumed_safe(self) -> None:
        assert classify("wibble wobble") is StatementKind.UNKNOWN
        assert classify("") is StatementKind.UNKNOWN


class TestParameters:
    def test_it_finds_named_parameters_in_order(self) -> None:
        assert parameters_in("SELECT * FROM t WHERE a = :region AND b > :since") == (
            "region",
            "since",
        )

    def test_it_deduplicates(self) -> None:
        assert parameters_in("SELECT :a, :a, :b") == ("a", "b")

    def test_a_postgres_cast_is_not_a_parameter(self) -> None:
        assert parameters_in("SELECT id::text FROM t") == ()

    def test_a_parameter_inside_a_literal_is_not_one(self) -> None:
        assert parameters_in("SELECT ':not_a_param' AS x") == ()

    def test_a_script_collects_parameters_across_statements(self) -> None:
        script = parse("SELECT :a; SELECT :b, :a")
        assert script.parameters == ["a", "b"]


class TestParsing:
    def test_an_empty_script_is_refused(self) -> None:
        for value in ("", "   ", "\n\n", ";;;"):
            with pytest.raises(BadRequestError, match="no SQL"):
                parse(value)

    def test_too_many_statements_is_refused_with_the_count(self) -> None:
        with pytest.raises(BadRequestError, match=f"limit is {MAX_STATEMENTS}"):
            parse("SELECT 1;" * (MAX_STATEMENTS + 1))

    def test_an_enormous_script_is_refused_before_a_driver_sees_it(self) -> None:
        with pytest.raises(BadRequestError, match="limit is"):
            parse("SELECT 1 " + "-- padding\n" * 30_000)

    def test_a_script_reports_whether_it_writes(self) -> None:
        assert not parse("SELECT 1; SELECT 2").writes
        assert parse("SELECT 1; DELETE FROM t").writes

    def test_statements_are_numbered_from_one(self) -> None:
        assert [s.index for s in parse("SELECT 1; SELECT 2; SELECT 3").statements] == [1, 2, 3]

    def test_the_summary_is_short_and_single_line(self) -> None:
        statement = parse("SELECT\n   a,\n   b\nFROM t").statements[0]
        assert statement.summary == "SELECT a, b FROM t"
        long = parse("SELECT " + ", ".join(f"col{i}" for i in range(40)) + " FROM t").statements[0]
        assert len(long.summary) == Statement.SUMMARY_LENGTH
        assert long.summary.endswith("…")
