"""Every awful file in the corpus, read and checked.

The roadmap's first acceptance criterion for Phase 11, executed: a corpus of
deliberately awful real-world files, each a test. `corpus.py` holds the files
and what reading each one correctly means; this runs them.

The assertions are deliberately specific. "It did not raise" is worth very
little for file ingestion -- the whole failure mode of the domain is a file
that loads cleanly and means something else. So a case pins the rows, the
columns, the types and, where it matters, the values.
"""

from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from shared_python.errors import ApplicationError

from service_ingestion import spec as spec_module
from service_ingestion.sniff import analyse


def _load_corpus():
    """Load the sibling corpus module by path.

    pytest runs with `--import-mode=importlib` and no `__init__.py` anywhere, so
    a bare `from corpus import ...` resolves against the rootdir rather than
    this directory and fails. Loading by path is what the rest of the
    repository does for the same reason -- see `test_generators.py`.
    """
    import importlib.util
    import sys

    path = pathlib.Path(__file__).with_name("corpus.py")
    spec = importlib.util.spec_from_file_location("ingestion_corpus", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `dataclasses` resolves a class's annotations
    # through `sys.modules[cls.__module__]`, and a module that is not there
    # yet fails with an unhelpful AttributeError on NoneType.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_corpus = _load_corpus()
CASES = _corpus.CASES
Case = _corpus.Case
by_name = _corpus.by_name

IDS = [case.name for case in CASES]


def _read(case: Case):
    """Analyse a case's file the way the upload path would."""
    payload = case.build()
    result = analyse(payload, file_name=case.file_name, overrides=case.answers)
    spec = spec_module.from_analysis(result, derived_from=case.file_name)
    if case.answers.get("columns"):
        for name, settled in case.answers["columns"].items():
            column = spec.column(name)
            if column is not None and settled.get("date_format"):
                column.date_format = settled["date_format"]
                column.type = "date"
    return result, spec


def _converted(result, spec) -> pd.DataFrame:
    frame, _ = spec_module.apply(result.frame, spec)
    return frame


def _reasons(result) -> str:
    return " || ".join(finding.reason for finding in result.all_findings)


@pytest.mark.parametrize("case", CASES, ids=IDS)
class TestTheCorpusReadsCorrectly:
    def test_it_reads_or_refuses_as_documented(self, case: Case) -> None:
        if case.expect_error:
            with pytest.raises(ApplicationError) as caught:
                _read(case)
            assert case.expect_error.lower() in str(caught.value).lower(), (
                f"{case.name}: {case.problem}"
            )
            return
        result, _ = _read(case)
        assert result is not None

    def test_the_format_is_what_it_is(self, case: Case) -> None:
        if case.expect_error or case.expect_format is None:
            pytest.skip("no format expectation")
        result, _ = _read(case)
        assert result.file_format == case.expect_format, case.problem

    def test_the_container_is_stripped(self, case: Case) -> None:
        if case.expect_error or case.expect_container is None:
            pytest.skip("not wrapped")
        result, _ = _read(case)
        assert result.container.startswith(case.expect_container), case.problem

    def test_it_finds_the_right_number_of_rows(self, case: Case) -> None:
        if case.expect_error or case.expect_rows is None:
            pytest.skip("no row expectation")
        result, _ = _read(case)
        assert len(result.frame) == case.expect_rows, (
            f"{case.name}: {case.problem}\nGot columns {list(result.frame.columns)}"
        )

    def test_it_finds_the_right_columns(self, case: Case) -> None:
        if case.expect_error or case.expect_columns is None:
            pytest.skip("no column expectation")
        result, _ = _read(case)
        assert tuple(str(name) for name in result.frame.columns) == case.expect_columns, (
            case.problem
        )

    def test_the_types_are_what_the_file_means(self, case: Case) -> None:
        if case.expect_error or not case.expect_types:
            pytest.skip("no type expectation")
        result, spec = _read(case)
        by_name = {column.name: column.type for column in spec.columns}
        for name, expected in case.expect_types.items():
            assert name in by_name, f"{case.name}: no column {name!r} in {list(by_name)}"
            assert by_name[name] == expected, (
                f"{case.name}: {case.problem}\n{name} typed {by_name[name]}, expected {expected}"
            )

    def test_the_values_survive_conversion(self, case: Case) -> None:
        if case.expect_error or not case.expect_values:
            pytest.skip("no value expectation")
        result, spec = _read(case)
        frame = _converted(result, spec)
        for name, expected in case.expect_values.items():
            assert name in frame.columns, f"{case.name}: no column {name!r}"
            actual = [
                None if value is None or (not isinstance(value, str) and pd.isna(value))
                else (str(value) if isinstance(value, (pd.Timestamp,)) else value)
                for value in frame[name].tolist()
            ]
            actual = [str(value) if hasattr(value, "isoformat") else value for value in actual]
            assert actual == expected, f"{case.name}: {case.problem}"

    def test_an_unanswerable_question_blocks(self, case: Case) -> None:
        """The requirement the phase turns on: never assume, ask."""
        if case.expect_error or case.expect_blocking is None:
            pytest.skip("nothing to block on")
        result, _ = _read(case)
        stages = [finding.stage for finding in result.blocked_by]
        assert case.expect_blocking in stages, (
            f"{case.name}: {case.problem}\nNothing blocked. Findings: {_reasons(result)}"
        )

    def test_it_reports_what_it_noticed(self, case: Case) -> None:
        if case.expect_error or case.expect_finding is None:
            pytest.skip("no finding expectation")
        result, _ = _read(case)
        stages = [finding.stage for finding in result.all_findings]
        assert case.expect_finding in stages, (
            f"{case.name}: expected a {case.expect_finding!r} finding, got {sorted(set(stages))}"
        )

    def test_the_reason_says_what_happened(self, case: Case) -> None:
        if case.expect_error or case.expect_reason is None:
            pytest.skip("no reason expectation")
        result, _ = _read(case)
        assert case.expect_reason.lower() in _reasons(result).lower(), (
            f"{case.name}: expected {case.expect_reason!r} in a finding.\n{_reasons(result)}"
        )


class TestTheCorpusItself:
    def test_it_is_big_enough_to_mean_something(self) -> None:
        """The roadmap asks for ~60 deliberately awful files."""
        assert len(CASES) >= 60, f"only {len(CASES)} cases"

    def test_every_case_says_what_is_wrong_with_it(self) -> None:
        """A fixture nobody can read is a fixture nobody will maintain."""
        for case in CASES:
            assert case.problem.strip().endswith("."), case.name
            assert len(case.problem) > 20, case.name

    def test_every_case_asserts_something(self) -> None:
        """'It did not raise' is worth very little here."""
        weak = [
            case.name
            for case in CASES
            if not any(
                (
                    case.expect_rows is not None,
                    case.expect_columns,
                    case.expect_types,
                    case.expect_values,
                    case.expect_blocking,
                    case.expect_finding,
                    case.expect_reason,
                    case.expect_error,
                )
            )
        ]
        assert weak == [], f"these cases only check that nothing raised: {weak}"

    def test_names_are_unique(self) -> None:
        names = [case.name for case in CASES]
        assert len(set(names)) == len(names)


class TestTheRoadmapsAcceptanceCriteria:
    """The four criteria Phase 11 names, each as a test that would fail."""

    def test_an_ambiguous_date_is_asked_about_never_assumed(self) -> None:
        case = by_name("ambiguous-dates")
        result, _ = _read(case)
        blocking = [finding for finding in result.blocked_by if finding.stage == "date_format"]
        assert blocking, "an ambiguous date must block rather than default"
        # And the question must be answerable: both readings named, in words.
        finding = blocking[0]
        assert len(finding.candidates) == 2
        assert "April" in finding.reason or "March" in finding.reason

    def test_answering_it_produces_the_answer_that_was_given(self) -> None:
        case = by_name("answered-ambiguous-dates")
        result, spec = _read(case)
        frame = _converted(result, spec)
        assert [str(value) for value in frame["when"]] == ["2026-04-03", "2026-06-05"]

    def test_a_sql_dump_yields_the_declared_schema(self) -> None:
        result, spec = _read(by_name("sql-dump"))
        by_column = {column.name: column.type for column in spec.columns}
        assert by_column["total"] == "decimal(12,2)", (
            "the dump declares decimal(12,2); inference would say float"
        )
        # And the declaration is cited rather than inferred.
        declared = [
            finding.reason
            for finding in result.all_findings
            if "CREATE TABLE" in finding.reason
        ]
        assert declared, "the schema should say it came from the declaration"

    def test_the_file_is_never_executed(self) -> None:
        """A dump is parsed. `DROP TABLE` is a statement like any other."""
        result, _ = _read(by_name("sql-dump"))
        assert "Nothing in the file was executed" in _reasons(result)

    def test_re_reading_with_a_stored_spec_gives_the_same_answer(self) -> None:
        """The fifth criterion: next month's file reuses last month's decisions."""
        case = by_name("answered-ambiguous-dates")
        _, spec = _read(case)

        # A second file with the same shape and *no* disambiguating value. Read
        # fresh it would block; read with the spec it does not.
        payload = b"id,when\n3,07/08/2026\n"
        fresh = analyse(payload, file_name="next-month.csv")
        assert any(f.stage == "date_format" for f in fresh.blocked_by)

        replayed = analyse(payload, file_name="next-month.csv", overrides=spec.overrides)
        assert not replayed.blocked_by, "a stored spec answers the question"
        frame, _ = spec_module.apply(replayed.frame, spec)
        assert str(frame["when"].iloc[0]) == "2026-08-07"


class TestTheAnalysisSampleNeverTruncatesAnImport:
    """The analysis reads a sample. Materialising must read the file.

    This was a real bug and the worst kind this phase can have: every upload
    was silently cut to `ANALYSIS_ROWS`, the load reported success, and the
    table looked entirely reasonable with three quarters of the rows missing.
    """

    def _rows(self, count: int) -> bytes:
        body = "".join(f"{index},row-{index}\n" for index in range(count))
        return ("id,name\n" + body).encode()

    def test_analysing_reads_only_the_sample(self) -> None:
        from service_ingestion.sniff.pipeline import ANALYSIS_ROWS

        payload = self._rows(ANALYSIS_ROWS + 500)
        sampled = analyse(payload, file_name="big.csv")
        assert len(sampled.frame) == ANALYSIS_ROWS

    def test_parsing_for_import_reads_every_row(self) -> None:
        from service_ingestion.parsers import parse_tabular_file
        from service_ingestion.sniff.pipeline import ANALYSIS_ROWS

        wanted = ANALYSIS_ROWS + 500
        parsed = parse_tabular_file(
            file_bytes=self._rows(wanted), file_type="csv", file_name="big.csv"
        )
        assert len(parsed.dataframe) == wanted, (
            "the import path must read the file, not the analysis sample"
        )
        assert parsed.metadata["row_count"] == wanted

    def test_asking_for_everything_is_explicit(self) -> None:
        """`limit=None` means the file; there is no safe default."""
        from service_ingestion.sniff.pipeline import ANALYSIS_ROWS

        payload = self._rows(ANALYSIS_ROWS + 500)
        assert len(analyse(payload, file_name="big.csv", limit=None).frame) == (
            ANALYSIS_ROWS + 500
        )
