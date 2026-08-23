"""The IR must mean exactly what the existing engine means.

Migrating twenty step types onto a new algebra is only safe if the two agree,
so every case here runs the step BOTH ways -- through the original
``STEP_APPLY_FUNCTIONS`` handler and through the IR -- and asserts the frames
match.

This is the same discipline as ``test_matches_engine.py`` in the lineage
service, which is the test that has caught the most real bugs in this project.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.from_steps import (
    EXTENSION_STEPS,
    compile_pipeline,
    compile_step,
    known_step_types,
)
from service_transformations.ir.nodes import Extension, Scan
from service_transformations.ir.pandas_backend import execute, register_extension
from service_transformations.steps import (
    ALL_STEP_TYPES,
    CONTEXT_STEP_APPLY_FUNCTIONS,
    STEP_APPLY_FUNCTIONS,
)

FRAME = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6],
        "region": ["eu ", "us", None, "eu ", "us", "apac"],
        "amount": [10.0, 250.0, 30.0, 10.0, None, 75.5],
        "label": ["a", "B", "c", "a", "D", None],
        "when": ["2026-01-01", "2026-02-01", None, "2026-01-01", "bad", "2026-03-05"],
    }
)

SCAN = Scan(
    "t",
    (("id", INT64), ("region", STRING), ("amount", FLOAT64), ("label", STRING),
     ("when", STRING)),
)


@pytest.fixture(autouse=True, scope="module")
def _extensions_delegate_to_the_original_handlers():
    """An Extension runs the very code the algebra could not model.

    Registering the original handler is not a shortcut -- it is the design: a
    step that resists modelling stays runnable and simply never pushes down.
    """
    for step_type, handler in STEP_APPLY_FUNCTIONS.items():

        def make(fn):
            def run(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
                result, _ = fn(frame, config)
                return result

            return run

        register_extension(step_type, make(handler))
    yield


def _run_original(step_type: str, config: dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    handler = STEP_APPLY_FUNCTIONS[step_type]
    result, _ = handler(frame.copy(), config)
    return result.reset_index(drop=True)


def _run_ir(step_type: str, config: dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    tree = compile_step(SCAN, step_type, config)
    return execute(tree, {"t": frame.copy()}).reset_index(drop=True)


def _compare(step_type: str, config: dict[str, Any]) -> None:
    original = _run_original(step_type, config, FRAME)
    through_ir = _run_ir(step_type, config, FRAME)

    assert list(through_ir.columns) == list(original.columns), (
        f"{step_type}: columns differ\n  engine={list(original.columns)}\n"
        f"  ir    ={list(through_ir.columns)}"
    )
    # Values, not storage: the IR path can produce a nullable dtype where the
    # original produced object, which is not a behavioural difference.
    left = original.astype("object").where(original.notna(), None)
    right = through_ir.astype("object").where(through_ir.notna(), None)
    pd.testing.assert_frame_equal(
        left.reset_index(drop=True),
        right.reset_index(drop=True),
        check_dtype=False,
        obj=step_type,
    )


CASES: list[tuple[str, dict[str, Any]]] = [
    ("select_columns", {"columns": ["id", "amount"]}),
    ("drop_columns", {"columns": ["label"]}),
    ("rename_columns", {"mappings": {"region": "market"}}),
    ("trim_strings", {"columns": ["region"]}),
    ("fill_nulls", {"strategy": "constant", "columns": ["amount"], "constant_value": 0}),
    ("drop_null_rows", {"how": "any", "columns": ["amount"]}),
    ("drop_null_rows", {"how": "any", "columns": ["region", "amount"]}),
    ("drop_null_rows", {"how": "all", "columns": ["region", "amount"]}),
    ("drop_null_rows", {"how": "any"}),
    ("remove_duplicates", {"subset": ["region"], "keep": "first"}),
    ("remove_duplicates", {"keep": "first"}),
    ("filter_rows", {"conditions": [{"column": "amount", "operator": "greater_than", "value": 20}]}),
    (
        "filter_rows",
        {
            "conditions": [
                {"column": "amount", "operator": "greater_or_equal", "value": 10},
                {"column": "region", "operator": "equals", "value": "us"},
            ]
        },
    ),
    ("filter_rows", {"conditions": [{"column": "region", "operator": "in", "value": ["us", "apac"]}]}),
    ("filter_rows", {"conditions": [{"column": "amount", "operator": "less_than", "value": 100}]}),
    ("sort_rows", {"columns": ["amount"], "ascending": True}),
    ("sort_rows", {"columns": ["amount"], "ascending": False}),
    ("sort_rows", {"columns": ["region", "amount"], "ascending": [True, False]}),
    ("limit_rows", {"count": 3}),
    ("limit_rows", {"count": 2, "offset": 2}),
    (
        "aggregate",
        {
            "group_by": ["region"],
            "aggregations": [
                {"column": "amount", "function": "sum", "alias": "total"},
                {"column": "id", "function": "count", "alias": "n"},
            ],
        },
    ),
    (
        "aggregate",
        {"group_by": ["region"], "aggregations": [{"column": "amount", "function": "max"}]},
    ),
    ("parse_dates", {"columns": ["when"]}),
    # Every aggregate the engine supports, run both ways. `count_distinct`,
    # `first` and `last` were missing from the IR entirely until a contract
    # guard compared the two allowlists.
    *[
        (
            "aggregate",
            {
                "group_by": ["region"],
                "aggregations": [{"column": "amount", "function": fn, "alias": "value"}],
            },
        )
        for fn in ("sum", "mean", "avg", "min", "max", "median", "std", "first", "last")
    ],
    (
        "aggregate",
        {
            "group_by": ["region"],
            "aggregations": [
                {"column": "label", "function": "count_distinct", "alias": "value"}
            ],
        },
    ),
    (
        "aggregate",
        {
            "group_by": ["region"],
            "aggregations": [{"column": "id", "function": "count", "alias": "value"}],
        },
    ),
]


@pytest.mark.parametrize(
    ("step_type", "config"), CASES, ids=[f"{t}:{i}" for i, (t, _) in enumerate(CASES)]
)
def test_ir_agrees_with_the_engine(step_type: str, config: dict[str, Any]) -> None:
    _compare(step_type, config)


class TestCoverage:
    def test_every_step_type_has_an_ir_mapping(self) -> None:
        # A step with no mapping cannot be planned, pushed down, or reasoned
        # about -- and would fail at run time rather than at build time.
        assert known_step_types() == set(ALL_STEP_TYPES)

    def test_the_engine_and_the_ir_cover_the_same_steps(self) -> None:
        engine = set(STEP_APPLY_FUNCTIONS) | set(CONTEXT_STEP_APPLY_FUNCTIONS)
        assert engine == set(ALL_STEP_TYPES)

    @pytest.mark.parametrize("step_type", sorted(EXTENSION_STEPS))
    def test_reshaping_steps_become_extensions(self, step_type: str) -> None:
        # Named explicitly so a future step cannot join this set by accident.
        node = compile_step(SCAN, step_type, {})
        assert isinstance(node, Extension)

    def test_extensions_still_run(self) -> None:
        # The escape hatch is only honest if the step actually works.
        config = {"column": "when", "delimiter": "-", "into": ["y", "m", "d"]}
        tree = compile_step(SCAN, "split_column", config)
        original = _run_original("split_column", config, FRAME)
        through_ir = execute(tree, {"t": FRAME.copy()})
        assert list(through_ir.columns) == list(original.columns)

    def test_a_multi_step_pipeline_folds_into_one_tree(self) -> None:
        steps = [
            {"type": "filter_rows", "config": {"conditions": [
                {"column": "amount", "operator": "greater_than", "value": 5}]}},
            {"type": "trim_strings", "config": {"columns": ["region"]}},
            {"type": "sort_rows", "config": {"columns": ["amount"], "ascending": False}},
            {"type": "limit_rows", "config": {"count": 3}},
        ]
        tree = compile_pipeline(SCAN, steps)
        result = execute(tree, {"t": FRAME.copy()})
        assert len(result) == 3
        assert list(result["amount"]) == sorted(
            [v for v in result["amount"]], reverse=True
        )

    def test_an_unknown_step_type_is_rejected_while_building(self) -> None:
        from service_transformations.ir.nodes import IRError

        with pytest.raises(IRError, match="No IR mapping"):
            compile_step(SCAN, "teleport_rows", {})
