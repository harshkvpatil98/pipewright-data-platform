"""Lineage derived from the IR must match lineage computed per step.

``columns.py`` knows what each of the twenty step types does to a column list.
``from_ir.py`` reads the same answer off the IR's schema propagation. Two
implementations of one question is two chances to disagree, so they are held
against each other over the corpus that already proves ``columns.py`` matches a
real pandas run -- which makes this transitively a check against reality.

Where they cannot agree, they must disagree *loudly*: a pivot produces columns
from data, so nothing static can name them, and both say so rather than
inventing names.
"""

from __future__ import annotations

import pandas as pd
import pytest

from service_lineage.columns import build_pipeline_lineage
from service_lineage.from_ir import can_derive, output_columns
from service_transformations.steps import STEP_APPLY_FUNCTIONS
from service_transformations.ir.from_steps import EXTENSION_STEPS
from service_transformations.ir.pandas_backend import register_extension

BASE = pd.DataFrame(
    {
        "id": [1, 2, 3, 4],
        "region": [" eu", "us", "eu", None],
        "gross": [100.0, 200.0, 50.0, 25.0],
        "discount": [10.0, 0.0, 5.0, None],
        "label": ["a", "b", "c", "d"],
    }
)


@pytest.fixture(autouse=True, scope="module")
def _extensions():
    for step_type, handler in STEP_APPLY_FUNCTIONS.items():
        def make(fn):
            def run(frame, config):
                result, _ = fn(frame, config)
                return result
            return run
        register_extension(step_type, make(handler))
    yield


def _run(frame: pd.DataFrame, steps: list[dict]) -> pd.DataFrame:
    for step in steps:
        handler = STEP_APPLY_FUNCTIONS[step["step_type"]]
        frame, _ = handler(frame, step["config"])
    return frame


CASES: list[tuple[str, list[dict]]] = [
    ("select", [{"step_type": "select_columns", "config": {"columns": ["id", "gross"]}}]),
    ("drop", [{"step_type": "drop_columns", "config": {"columns": ["label"]}}]),
    ("rename", [{"step_type": "rename_columns", "config": {"mappings": {"gross": "revenue"}}}]),
    ("trim", [{"step_type": "trim_strings", "config": {"columns": ["region"]}}]),
    (
        "fill_then_filter",
        [
            {"step_type": "fill_nulls", "config": {
                "strategy": "constant", "columns": ["discount"], "constant_value": 0}},
            {"step_type": "filter_rows", "config": {"conditions": [
                {"column": "gross", "operator": "greater_than", "value": 30}]}},
        ],
    ),
    (
        "drop_nulls_then_sort",
        [
            {"step_type": "drop_null_rows", "config": {"how": "any", "columns": ["region"]}},
            {"step_type": "sort_rows", "config": {"columns": ["gross"], "ascending": False}},
        ],
    ),
    ("dedupe", [{"step_type": "remove_duplicates", "config": {"subset": ["region"], "keep": "first"}}]),
    ("limit", [{"step_type": "limit_rows", "config": {"count": 2}}]),
    (
        "aggregate",
        [{"step_type": "aggregate", "config": {
            "group_by": ["region"],
            "aggregations": [{"column": "gross", "function": "sum", "alias": "total"}]}}],
    ),
    (
        "aggregate_default_alias",
        [{"step_type": "aggregate", "config": {
            "group_by": ["region"],
            "aggregations": [{"column": "gross", "function": "max"}]}}],
    ),
    ("cast", [{"step_type": "cast_column_types", "config": {"mappings": {"gross": "int"}}}]),
    (
        "long_chain",
        [
            {"step_type": "trim_strings", "config": {"columns": ["region"]}},
            {"step_type": "drop_null_rows", "config": {"how": "any", "columns": ["region"]}},
            {"step_type": "rename_columns", "config": {"mappings": {"gross": "revenue"}}},
            {"step_type": "select_columns", "config": {"columns": ["id", "region", "revenue"]}},
            {"step_type": "sort_rows", "config": {"columns": ["revenue"], "ascending": False}},
            {"step_type": "limit_rows", "config": {"count": 2}},
        ],
    ),
]


@pytest.mark.parametrize("label,steps", CASES, ids=[c[0] for c in CASES])
def test_ir_derives_the_same_columns_as_the_per_step_implementation(
    label: str, steps: list[dict]
) -> None:
    per_step = build_pipeline_lineage(base_columns=list(BASE.columns), steps=steps)
    from_ir = output_columns(list(BASE.columns), steps)
    assert from_ir == per_step.output_columns, label


@pytest.mark.parametrize("label,steps", CASES, ids=[c[0] for c in CASES])
def test_both_match_what_pandas_actually_produces(label: str, steps: list[dict]) -> None:
    # The property that matters. Two predictions agreeing with each other but
    # not with reality would be worse than one prediction.
    actual = [str(column) for column in _run(BASE.copy(), steps).columns]
    assert output_columns(list(BASE.columns), steps) == actual, label


class TestHonestLimits:
    @pytest.mark.parametrize("step_type", sorted(EXTENSION_STEPS))
    def test_reshaping_steps_are_not_statically_predictable(self, step_type: str) -> None:
        # A pivot names columns after the DATA, so no static analysis can know
        # them. The IR carries them as an Extension whose schema is unknown.
        from service_transformations.ir.nodes import Extension
        from service_lineage.from_ir import build_tree

        tree = build_tree(list(BASE.columns), [{"step_type": step_type, "config": {}}])
        assert isinstance(tree, Extension)

    def test_a_pipeline_of_known_steps_can_always_be_derived(self) -> None:
        assert can_derive(list(BASE.columns), CASES[-1][1])

    def test_an_unknown_step_type_cannot_be_derived(self) -> None:
        # It returns False rather than raising, so a caller can fall back to
        # the per-step implementation instead of failing the request.
        assert not can_derive(list(BASE.columns), [{"step_type": "teleport", "config": {}}])
