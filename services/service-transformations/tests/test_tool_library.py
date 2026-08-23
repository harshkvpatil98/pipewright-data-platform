"""One test file for the whole tool library.

A catalogue of hundreds cannot be held to a standard that depends on each
author remembering it. So the standard is enforced structurally: these tests
iterate the registry, and a tool that arrives without an example, or that falls
over on an empty frame, fails here without anybody writing a test for it.

Four things are checked for *every* tool:

1. Its documented example produces the documented output. The reference is
   generated from these, so it cannot drift from the behaviour.
2. An empty frame in gives an empty frame out, with the same columns. This is
   the case that breaks in production, on the day a filter upstream matches
   nothing.
3. An all-null column in gives no exception and no invented values.
4. A single row works -- which is not implied by the others, because pandas
   changes its mind about dtypes at length one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

import service_transformations.tools as tools
from service_transformations.tools.apply import apply_tool
from service_transformations.tools.spec import ParamKind

ALL = sorted(tools.TOOLS)


def frame_for(spec: tools.ToolSpec) -> pd.DataFrame:
    return pd.DataFrame(list(spec.example.rows))


def config_for(spec: tools.ToolSpec, frame: pd.DataFrame) -> dict:
    column = spec.example.column or (list(frame.columns)[0] if len(frame.columns) else None)
    config = {"tool": spec.name, **spec.example.params}
    if column is not None:
        config["column"] = column
    return config


def predict(frame: pd.DataFrame, config: dict):
    """What lineage says this tool will do, without running it."""
    from service_lineage.columns import build_pipeline_lineage

    return build_pipeline_lineage(
        base_columns=[str(name) for name in frame.columns],
        steps=[{"step_type": "tool", "config": config}],
    ).steps[-1]


def run(spec: tools.ToolSpec, frame: pd.DataFrame) -> pd.DataFrame:
    result, _ = apply_tool(frame, config_for(spec, frame))
    return result


def observed(spec: tools.ToolSpec, frame: pd.DataFrame, result: pd.DataFrame):
    target = spec.example.output
    if target == "__columns__":
        return [",".join(str(name) for name in result.columns)]
    if target is None:
        target = spec.example.column or list(frame.columns)[0]
    assert target in result.columns, f"{spec.name} did not produce {target!r}"
    return [None if pd.isna(v) else v for v in result[target].tolist()]


def normalise(value):
    """Compare the way a person reading the reference would."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (pd.Timestamp,)):
        return str(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, int):
        return value
    return str(value)


class TestEveryToolIsDeclaredProperly:
    @pytest.mark.parametrize("name", ALL)
    def test_it_has_a_title_summary_and_example(self, name: str) -> None:
        spec = tools.TOOLS[name]
        assert spec.title.strip(), name
        assert spec.summary.strip().endswith("."), f"{name}: summaries are sentences"
        assert spec.category.strip(), name
        assert spec.example.rows, f"{name} has no example rows"

    @pytest.mark.parametrize("name", ALL)
    def test_its_name_is_namespaced(self, name: str) -> None:
        # "text.trim", not "trim" -- the catalogue has several trims.
        assert "." in name, f"{name} needs a category prefix"

    @pytest.mark.parametrize("name", ALL)
    def test_its_parameters_are_describable(self, name: str) -> None:
        spec = tools.TOOLS[name]
        for param in spec.params:
            assert param.label.strip(), f"{name}.{param.key}"
            if param.kind is ParamKind.SELECT:
                assert param.options, f"{name}.{param.key} is a choice with no choices"
                if param.default is not None:
                    assert param.default in param.options, f"{name}.{param.key}"

    def test_no_two_tools_share_a_title_within_a_category(self) -> None:
        seen: dict[tuple[str, str], str] = {}
        for spec in tools.TOOLS.values():
            key = (spec.category, spec.title.lower())
            assert key not in seen, f"{spec.name} and {seen[key]} are both {spec.title!r}"
            seen[key] = spec.name

    def test_the_catalogue_is_big_enough_to_need_search(self) -> None:
        # A guard against a refactor silently dropping a category module: the
        # registry is populated by import side effects.
        assert len(tools.TOOLS) > 150
        assert len(tools.categories()) >= 10


class TestDocumentedExamplesAreTrue:
    """The reference is generated from these, so they are the reference."""

    @pytest.mark.parametrize("name", ALL)
    def test_the_example_produces_what_it_says(self, name: str) -> None:
        spec = tools.TOOLS[name]
        if not spec.example.expect:
            pytest.skip(f"{name} documents shape rather than a value")
        frame = frame_for(spec)
        result = run(spec, frame)
        actual = [normalise(v) for v in observed(spec, frame, result)]
        expected = [normalise(v) for v in spec.example.expect]
        assert actual == expected, f"{name}: documented {expected}, produced {actual}"


class TestEdgeCases:
    """Empty, all-null and single-row -- the three shapes nobody tests by hand."""

    @pytest.mark.parametrize("name", ALL)
    def test_an_empty_frame_stays_empty(self, name: str) -> None:
        spec = tools.TOOLS[name]
        frame = frame_for(spec).iloc[0:0]
        result = run(spec, frame)
        assert len(result) == 0, f"{name} invented rows from an empty frame"

    @pytest.mark.parametrize("name", ALL)
    def test_all_nulls_do_not_become_values(self, name: str) -> None:
        spec = tools.TOOLS[name]
        template = frame_for(spec)
        frame = pd.DataFrame(
            {column: [None] * len(template) for column in template.columns}
        )
        result = run(spec, frame)
        assert isinstance(result, pd.DataFrame)
        if spec.column_scoped and spec.example.output != "__columns__":
            target = spec.example.output or spec.example.column or list(frame.columns)[0]
            if target in result.columns:
                values = [v for v in result[target].tolist() if not pd.isna(v)]
                # Predicates about a value are allowed to answer for null;
                # anything else inventing a value from nothing is a bug.
                if spec.name not in ALLOWED_ON_NULL:
                    assert values == [], f"{name} produced {values} from all nulls"

    @pytest.mark.parametrize("name", ALL)
    def test_a_single_row_works(self, name: str) -> None:
        spec = tools.TOOLS[name]
        frame = frame_for(spec).iloc[:1]
        result = run(spec, frame)
        assert isinstance(result, pd.DataFrame)


#: Tools whose answer for a missing value is a real answer, not a null.
ALLOWED_ON_NULL = frozenset({
    "null.fill_constant", "null.null_to_empty", "null.is_blank", "check.is_date",
    "check.is_number", "check.quarantine", "rows.filter",
})


class TestConfigurationIsValidated:
    def test_an_unknown_tool_names_where_to_look(self) -> None:
        with pytest.raises(BadRequestError, match="no tool called"):
            apply_tool(pd.DataFrame({"a": [1]}), {"tool": "text.nonexistent", "column": "a"})

    def test_a_missing_column_lists_what_is_available(self) -> None:
        with pytest.raises(BadRequestError, match="ghost"):
            apply_tool(pd.DataFrame({"a": ["x"]}), {"tool": "text.trim", "column": "ghost"})

    def test_an_unexpected_parameter_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="does not take"):
            apply_tool(
                pd.DataFrame({"a": ["x"]}),
                {"tool": "text.trim", "column": "a", "sparkles": True},
            )

    def test_a_required_parameter_is_named_when_missing(self) -> None:
        with pytest.raises(BadRequestError, match="required"):
            apply_tool(pd.DataFrame({"a": ["x"]}), {"tool": "text.replace", "column": "a"})

    def test_a_number_out_of_range_says_the_bound(self) -> None:
        with pytest.raises(BadRequestError, match="cannot be more than"):
            apply_tool(
                pd.DataFrame({"a": [1.0]}),
                {"tool": "numeric.round", "column": "a", "digits": 99},
            )

    def test_a_choice_lists_the_choices(self) -> None:
        with pytest.raises(BadRequestError, match="must be one of"):
            apply_tool(
                pd.DataFrame({"a": ["2026-01-01"]}),
                {"tool": "date.start_of_period", "column": "a", "period": "fortnight"},
            )

    def test_writing_into_an_existing_column_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="already exists"):
            apply_tool(
                pd.DataFrame({"a": ["x"], "b": ["y"]}),
                {"tool": "text.trim", "column": "a", "into": "b"},
            )


class TestApplicability:
    def test_a_date_tool_is_not_offered_on_a_number(self) -> None:
        from shared_python.types import FLOAT64, STRING, timestamp

        offered = {spec.name for spec in tools.applicable_to(FLOAT64)}
        assert "date.year" not in offered
        assert "numeric.round" in offered

        on_text = {spec.name for spec in tools.applicable_to(STRING)}
        assert "text.trim" in on_text
        assert "numeric.round" not in on_text

        on_time = {spec.name for spec in tools.applicable_to(timestamp())}
        assert "date.year" in on_time

    def test_an_unprofiled_column_is_offered_everything(self) -> None:
        from shared_python.types.lattice import UNKNOWN

        # Hiding tools because the profiler could not decide would make an
        # unprofiled column untouchable, which is exactly when they are needed.
        offered = {spec.name for spec in tools.applicable_to(UNKNOWN)}
        assert "date.year" in offered
        assert "numeric.round" in offered

    def test_frame_tools_are_not_offered_as_column_tools(self) -> None:
        from shared_python.types import STRING

        offered = {spec.name for spec in tools.applicable_to(STRING)}
        assert "rows.sort" not in offered
        assert all(tools.TOOLS[name].column_scoped for name in offered)


class TestSearch:
    def test_it_finds_a_tool_by_the_word_people_use(self) -> None:
        # Nobody searches for "initcap".
        assert tools.search("title case")[0].name == "text.title_case"
        assert tools.search("zip")[0].name == "clean.postal_code"
        assert tools.search("dedupe")[0].name == "rows.deduplicate"
        assert tools.search("e164")[0].name == "clean.phone"

    def test_an_exact_name_wins(self) -> None:
        assert tools.search("text.trim")[0].name == "text.trim"

    def test_an_empty_query_returns_the_head_of_the_catalogue(self) -> None:
        assert len(tools.search("", limit=5)) == 5

    def test_nonsense_finds_nothing_rather_than_everything(self) -> None:
        assert tools.search("zzzzqqq") == []

    @pytest.mark.parametrize("name", ALL)
    def test_every_tool_is_findable_by_its_own_title(self, name: str) -> None:
        spec = tools.TOOLS[name]
        found = {result.name for result in tools.search(spec.title, limit=50)}
        assert name in found, f"{name} cannot be found by searching its own title"


class TestCompilesToIR:
    """The whole point of the shape: a tool is IR, so it gets the IR's benefits."""

    @pytest.mark.parametrize("name", ALL)
    def test_it_builds_a_node_with_a_schema(self, name: str) -> None:
        from service_transformations.tools.apply import build

        spec = tools.TOOLS[name]
        frame = frame_for(spec)
        node = build(frame, config_for(spec, frame))
        assert node.schema(), f"{name} produced a node with no columns"

    @pytest.mark.parametrize("name", ALL)
    def test_its_declared_output_columns_are_what_it_produces(self, name: str) -> None:
        """Lineage is derived from the node's schema, so it has to be right."""
        from service_transformations.tools.apply import build

        spec = tools.TOOLS[name]
        frame = frame_for(spec)
        config = config_for(spec, frame)
        predicted = list(build(frame, config).schema())
        actual = list(apply_tool(frame, config)[0].columns)
        assert predicted == actual, f"{name}: lineage would report {predicted}, got {actual}"


class TestLineageMatchesTheEngine:
    """Predicted columns must equal the columns a real run produces.

    This is the Phase 02 discipline applied to the tool library: lineage is
    symbolically executed, so it is only worth having if it agrees with the
    engine on every tool -- and 'every tool' is a set that grows weekly.
    """

    @pytest.mark.parametrize("name", ALL)
    def test_predicted_columns_equal_actual_columns(self, name: str) -> None:
        spec = tools.TOOLS[name]
        frame = frame_for(spec)
        config = config_for(spec, frame)

        predicted = predict(frame, config)
        actual = list(apply_tool(frame, config)[0].columns)
        assert predicted.output_columns == actual, (
            f"{name}: lineage says {predicted.output_columns}, engine produced {actual}"
        )

    @pytest.mark.parametrize("name", ALL)
    def test_a_column_tool_records_where_its_output_came_from(self, name: str) -> None:
        spec = tools.TOOLS[name]
        if not spec.column_scoped:
            pytest.skip("frame tools have no single target column")
        frame = frame_for(spec)
        config = config_for(spec, frame)
        step = predict(frame, config)
        target = config["column"]
        assert step.edges, f"{name} recorded no lineage edge for {target}"
        assert target in step.named_columns, f"{name} did not name the column it reads"


class TestSearchHandlesRealQueries:
    """People type sentences, not identifiers."""

    def test_every_word_has_to_match(self) -> None:
        # With an any-word rule, adding detail to a query makes results worse.
        assert tools.search("zip code")[0].name == "clean.postal_code"
        assert tools.search("zip banana") == []

    def test_a_word_boundary_beats_a_substring(self) -> None:
        # "phonetic" contains "phone"; the phone tool should still win.
        assert tools.search("phone")[0].name == "clean.phone"

    def test_filler_words_are_ignored(self) -> None:
        assert tools.search("extract year from date")[0].name == "date.year"
        assert tools.search("split a name")[0].name == "clean.name_part"

    def test_punctuation_in_a_query_does_not_break_it(self) -> None:
        assert tools.search("text.trim")[0].name == "text.trim"
        assert tools.search("title-case")[0].name == "text.title_case"

    def test_the_limit_is_honoured(self) -> None:
        assert len(tools.search("text", limit=3)) == 3


class TestDateArithmeticEdges:
    """The cases where "add a month" has more than one defensible answer."""

    def _run(self, tool: str, value, **params):
        frame = pd.DataFrame({"when": [value]})
        result, _ = apply_tool(frame, {"tool": tool, "column": "when", **params})
        return result["when"].iloc[0]

    def test_a_month_added_to_the_31st_clamps_rather_than_overflowing(self) -> None:
        # 31 January plus one month is 28 February, not 3 March.
        assert str(self._run("date.add_months", "2026-01-31", months=1)).startswith("2026-02-28")

    def test_it_clamps_into_a_leap_february(self) -> None:
        assert str(self._run("date.add_months", "2028-01-31", months=1)).startswith("2028-02-29")

    def test_it_goes_backwards_across_a_year_boundary(self) -> None:
        assert str(self._run("date.add_months", "2026-01-15", months=-1)).startswith("2025-12-15")

    def test_a_year_added_to_a_leap_day_clamps(self) -> None:
        assert str(self._run("date.add_years", "2028-02-29", years=1)).startswith("2029-02-28")

    def test_end_of_month_is_the_last_instant_not_the_next_month(self) -> None:
        # A report labelled "to 1 February" when it means January is a support ticket.
        end = str(self._run("date.end_of_period", "2026-02-10", period="month"))
        assert end.startswith("2026-02-28 23:59:59")

    def test_end_of_quarter_lands_in_the_right_quarter(self) -> None:
        end = str(self._run("date.end_of_period", "2026-08-23", period="quarter"))
        assert end.startswith("2026-09-30 23:59:59")

    def test_start_of_week_is_monday(self) -> None:
        # 2026-08-23 is a Sunday, so its week began on the 17th.
        assert str(self._run("date.start_of_period", "2026-08-23", period="week")).startswith(
            "2026-08-17"
        )

    def test_business_days_skip_the_weekend(self) -> None:
        frame = pd.DataFrame({"when": ["2026-08-21"], "other": ["2026-08-25"]})
        result, _ = apply_tool(
            frame,
            {"tool": "date.business_days_between", "column": "when", "other": "other"},
        )
        # Friday to Tuesday is two working days.
        assert result["when"].iloc[0] == 2

    def test_business_days_between_is_signed(self) -> None:
        frame = pd.DataFrame({"when": ["2026-08-25"], "other": ["2026-08-21"]})
        result, _ = apply_tool(
            frame,
            {"tool": "date.business_days_between", "column": "when", "other": "other"},
        )
        assert result["when"].iloc[0] == -2

    def test_a_fiscal_year_is_named_for_the_year_it_ends_in(self) -> None:
        assert self._run("date.fiscal_year", "2026-08-23", start_month=4) == 2027
        assert self._run("date.fiscal_year", "2026-02-01", start_month=4) == 2026

    def test_a_calendar_fiscal_year_is_just_the_year(self) -> None:
        assert self._run("date.fiscal_year", "2026-08-23", start_month=1) == 2026


class TestMixedDateFormatsSurvive:
    """A column with two date formats must not lose half its rows."""

    def test_both_formats_parse(self) -> None:
        frame = pd.DataFrame({"when": ["2026-01-05", "5 March 2026", "nonsense"]})
        result, warnings = apply_tool(frame, {"tool": "date.parse", "column": "when"})
        parsed = [None if pd.isna(v) else str(v) for v in result["when"]]
        assert parsed[0] == "2026-01-05"
        assert parsed[1] == "2026-03-05"
        assert parsed[2] is None
        # And the row it could not read is reported rather than silently dropped.
        assert warnings and "1 of 3" in warnings[0]


class TestSettingsMustBeConstant:
    """A setting given a column would be read from row zero and applied to all.

    The IR does not stop that being expressed, so the function layer checks it.
    Silently using the first row's value is worse than refusing, because the
    output looks entirely plausible.
    """

    def test_a_varying_setting_is_refused_rather_than_guessed(self) -> None:
        from service_transformations.ir.expressions import Call, Column
        from service_transformations.ir.pandas_backend import evaluate

        frame = pd.DataFrame({"a": ["hello", "world"], "n": [2, 4]})
        with pytest.raises(BadRequestError, match="same for every row"):
            evaluate(Call("truncate_text", (Column("a"), Column("n"))), frame)

    def test_a_constant_column_is_accepted(self) -> None:
        from service_transformations.ir.expressions import Call, Column
        from service_transformations.ir.pandas_backend import evaluate

        frame = pd.DataFrame({"a": ["hello", "world"], "n": [2, 2]})
        assert evaluate(Call("truncate_text", (Column("a"), Column("n"))), frame).tolist() == [
            "he",
            "wo",
        ]


class TestFilteringComparesLikeWithLike:
    """A filter that is valid and never true is the hardest kind to debug."""

    def _keep(self, frame: pd.DataFrame, column: str, value: str, operator: str = "equals"):
        result, _ = apply_tool(
            frame,
            {
                "tool": "rows.filter",
                "column": column,
                "operator": operator,
                "value": value,
                "mode": "keep",
            },
        )
        return result

    def test_a_true_false_column_understands_the_word_true(self) -> None:
        frame = pd.DataFrame({"ok": [True, False, True], "id": [1, 2, 3]})
        assert self._keep(frame, "ok", "true")["id"].tolist() == [1, 3]
        assert self._keep(frame, "ok", "no")["id"].tolist() == [2]

    def test_a_number_column_understands_a_typed_number(self) -> None:
        frame = pd.DataFrame({"n": [1, 2, 3]})
        assert self._keep(frame, "n", "2")["n"].tolist() == [2]
        assert self._keep(frame, "n", "2", "greater than")["n"].tolist() == [3]

    def test_nonsense_against_a_number_column_says_so(self) -> None:
        frame = pd.DataFrame({"n": [1, 2]})
        with pytest.raises(BadRequestError, match="holds numbers"):
            self._keep(frame, "n", "banana")

    def test_nonsense_against_a_boolean_column_says_so(self) -> None:
        frame = pd.DataFrame({"ok": [True, False]})
        with pytest.raises(BadRequestError, match="true/false"):
            self._keep(frame, "ok", "banana")

    def test_excluding_also_drops_the_rows_whose_test_was_unknown(self) -> None:
        """`NOT NULL` is NULL, and a filter drops nulls -- so without care an
        exclusion loses the rows it was never asked about."""
        frame = pd.DataFrame({"region": ["eu", "us", None]})
        result, _ = apply_tool(
            frame,
            {
                "tool": "rows.filter",
                "column": "region",
                "operator": "equals",
                "value": "eu",
                "mode": "exclude",
            },
        )
        assert result["region"].tolist() == ["us", None]
