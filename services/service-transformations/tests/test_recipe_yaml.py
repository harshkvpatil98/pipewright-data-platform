"""Recipes round-tripping through YAML.

The acceptance criterion is "lossless for every recipe in the test corpus", so
the corpus is the test: every step type the platform has, plus a sample of the
tool library, plus the shapes that break naive serialisers.
"""

from __future__ import annotations

import pytest
import yaml

from shared_python.errors import BadRequestError

import service_transformations.tools as tools
from service_transformations.contracts import SUPPORTED_TRANSFORMATION_STEP_TYPES
from service_transformations.recipe_yaml import (
    FORMAT_VERSION,
    MAX_STEPS,
    from_yaml,
    steps_from_yaml,
    to_yaml,
)


def corpus() -> list[list[dict]]:
    """Every step type, plus the shapes that catch a naive implementation."""
    recipes: list[list[dict]] = [
        [],
        [{"step_type": "trim_strings", "config": {"columns": ["a", "b"]}}],
        [{"step_type": "rename_columns", "config": {"mappings": {"a": "b"}}}],
        [
            {"step_type": "filter_rows", "config": {
                "conditions": [{"column": "region", "operator": "equals", "value": "eu"}]
            }},
            {"step_type": "sort_rows", "config": {"columns": ["amount"], "ascending": False}},
            {"step_type": "limit_rows", "config": {"limit": 100}},
        ],
        [{"step_type": "aggregate", "config": {
            "group_by": ["region"],
            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
        }}],
        # Nesting, empty containers, unicode, and values that look like YAML.
        [{"step_type": "replace_values", "config": {
            "column": "note",
            "replacements": [
                {"find": "yes", "replace": "true"},
                {"find": "", "replace": None},
                {"find": "café", "replace": "cafe"},
                {"find": "3.10", "replace": "3.1"},
            ],
        }}],
        # A formula with quotes, a colon and a newline.
        [{"step_type": "derive_column", "config": {
            "target_column": "label",
            "formula": '=IF([region]="eu", "Europe: west", "Other")',
        }}],
        [{"step_type": "derive_column", "config": {
            "target_column": "multi",
            "expression": "a\n+ b\n+ c",
        }}],
        # Tool steps, whose name is hoisted out of the config.
        [{"step_type": "tool", "config": {"tool": "text.trim", "column": "name"}}],
        [{"step_type": "tool", "config": {
            "tool": "date.add_months", "column": "when", "months": -3, "into": "before"
        }}],
        [{"step_type": "tool", "config": {"tool": "rows.deduplicate", "columns": [], "keep": "last"}}],
        # A step with a name of its own.
        [{"step_type": "trim_strings", "config": {"columns": ["a"]}, "name": "Tidy up"}],
    ]
    # A sample of the tool library, so the corpus grows with it.
    for spec in list(tools.TOOLS.values())[::17]:
        config = {"tool": spec.name, "column": "value", **spec.example.params}
        recipes.append([{"step_type": "tool", "config": config}])
    return recipes


class TestRoundTrip:
    @pytest.mark.parametrize("steps", corpus(), ids=range(len(corpus())))
    def test_steps_survive_yaml_and_come_back_identical(self, steps: list[dict]) -> None:
        assert steps_from_yaml(to_yaml(steps)) == steps

    @pytest.mark.parametrize("steps", corpus(), ids=range(len(corpus())))
    def test_the_text_is_stable_across_a_second_pass(self, steps: list[dict]) -> None:
        # Edit the YAML, the recipe updates; edit the recipe, the YAML updates.
        # Without this, every save produces a diff whether or not anything changed.
        first = to_yaml(steps)
        assert to_yaml(steps_from_yaml(first)) == first

    def test_metadata_survives(self) -> None:
        text = to_yaml(
            [{"step_type": "trim_strings", "config": {"columns": ["a"]}}],
            name="Clean customers",
            description="Trim the imported names.",
            dataset="customers",
        )
        recipe = from_yaml(text)
        assert recipe["name"] == "Clean customers"
        assert recipe["description"] == "Trim the imported names."
        assert recipe["dataset"] == "customers"

    def test_an_empty_recipe_round_trips(self) -> None:
        assert steps_from_yaml(to_yaml([])) == []


class TestItReadsAsCode:
    def test_a_tool_step_names_its_tool_at_the_top(self) -> None:
        text = to_yaml([{"step_type": "tool", "config": {"tool": "text.trim", "column": "a"}}])
        # `- step: tool` followed by `tool: text.trim` reads as what happens;
        # burying the name in `with:` reads as a list of "tool".
        assert "step: tool" in text
        assert "tool: text.trim" in text
        assert text.index("tool: text.trim") < text.index("with:")

    def test_a_multi_line_value_is_a_literal_block(self) -> None:
        text = to_yaml(
            [{"step_type": "derive_column", "config": {"target_column": "x", "expression": "a\n+ b"}}]
        )
        assert "|-" in text or "|" in text
        assert "\\n" not in text

    def test_nothing_is_written_in_flow_style(self) -> None:
        # `{a: 1, b: 2}` on one line is a single-line diff for any change.
        text = to_yaml([{"step_type": "rename_columns", "config": {"mappings": {"a": "b", "c": "d"}}}])
        assert "{" not in text
        assert "[" not in text

    def test_the_version_leads_the_document(self) -> None:
        text = to_yaml([])
        assert text.startswith(f"version: {FORMAT_VERSION}")

    def test_it_is_plain_yaml_with_no_python_tags(self) -> None:
        text = to_yaml([{"step_type": "limit_rows", "config": {"limit": 10}}])
        assert "!!python" not in text
        assert yaml.safe_load(text)["steps"][0]["with"]["limit"] == 10


class TestRefusals:
    def test_empty_input_is_refused(self) -> None:
        for value in ("", "   ", "\n"):
            with pytest.raises(BadRequestError, match="no recipe"):
                from_yaml(value)

    def test_broken_yaml_reports_where(self) -> None:
        with pytest.raises(BadRequestError, match="not valid YAML"):
            from_yaml("steps:\n  - step: x\n   bad indent: 1")

    def test_a_list_at_the_top_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="mapping"):
            from_yaml("- step: trim_strings")

    def test_a_newer_format_version_is_refused_rather_than_guessed(self) -> None:
        with pytest.raises(BadRequestError, match="reads up to version"):
            from_yaml(f"version: {FORMAT_VERSION + 1}\nsteps: []")

    def test_an_unknown_top_level_key_is_named(self) -> None:
        with pytest.raises(BadRequestError, match="schedule"):
            from_yaml("version: 1\nschedule: daily\nsteps: []")

    def test_a_missing_steps_list_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="`steps:` list"):
            from_yaml("version: 1\nname: x")

    def test_an_unknown_step_type_lists_the_known_ones(self) -> None:
        with pytest.raises(BadRequestError, match="does not have"):
            from_yaml("version: 1\nsteps:\n  - step: teleport")

    def test_an_unknown_key_on_a_step_is_named(self) -> None:
        with pytest.raises(BadRequestError, match="Step 1 does not have: colour"):
            from_yaml("version: 1\nsteps:\n  - step: trim_strings\n    colour: red")

    def test_a_tool_step_without_a_tool_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="does not say which tool"):
            from_yaml("version: 1\nsteps:\n  - step: tool\n    with:\n      column: a")

    def test_a_tool_named_on_a_non_tool_step_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="names a tool but is a"):
            from_yaml("version: 1\nsteps:\n  - step: trim_strings\n    tool: text.trim")

    def test_too_many_steps_is_refused(self) -> None:
        body = "\n".join("  - step: limit_rows" for _ in range(MAX_STEPS + 1))
        with pytest.raises(BadRequestError, match=f"limit is {MAX_STEPS}"):
            from_yaml(f"version: 1\nsteps:\n{body}")

    def test_a_value_yaml_cannot_carry_is_refused_on_the_way_out(self) -> None:
        # Emitting a Python-specific tag would make a file only this platform
        # can read back, which is the opposite of the point.
        class Odd:
            pass

        with pytest.raises(BadRequestError, match="cannot be written as YAML"):
            to_yaml([{"step_type": "limit_rows", "config": {"limit": Odd()}}])

    def test_the_refusal_names_the_setting(self) -> None:
        class Odd:
            pass

        with pytest.raises(BadRequestError, match="nested.inner"):
            to_yaml([{"step_type": "limit_rows", "config": {"nested": {"inner": Odd()}}}])


class TestCoverage:
    def test_every_step_type_can_be_written_and_read(self) -> None:
        # A step type that cannot round-trip is a recipe somebody cannot put in
        # git, and the failure would only show up when they tried.
        for step_type in SUPPORTED_TRANSFORMATION_STEP_TYPES:
            config = {"tool": "text.trim", "column": "a"} if step_type == "tool" else {"a": 1}
            steps = [{"step_type": step_type, "config": config}]
            assert steps_from_yaml(to_yaml(steps)) == steps
