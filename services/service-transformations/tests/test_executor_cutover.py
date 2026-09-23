"""The IR is the only executor (P9 cutover of the Phase 08 decision).

`apply_single_step` now compiles every step to IR and runs it on the pandas
backend. These pin what the cutover promised: whole pipelines produce what the
original per-step handlers produced (the handlers are the oracle, exactly as in
`test_ir_from_steps.py`); steps the algebra does not model still run, as
Extensions backed by the original code, and still warn; a lossy native step
warns generically; configuration mistakes still get the original, field-naming
messages; and join/union still reach their sibling dataset.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from service_transformations.executor import (
    EXTENSION_BACKED,
    apply_single_step,
    apply_transformation_steps,
    apply_transformation_steps_with_outcomes,
)
from service_transformations.schemas import TransformationStep
from service_transformations.steps import STEP_APPLY_FUNCTIONS, StepContext
from service_transformations.validators import validate_steps_json
from shared_python.errors import BadRequestError

FRAME = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6],
        "region": ["eu ", "us", None, "eu ", "us", "apac"],
        "amount": [10.0, 250.0, 30.0, 10.0, None, 75.5],
        "label": ["a", "B", "c", "a", "D", None],
        "when": ["2026-01-01", "2026-02-01", None, "2026-01-01", "bad", "2026-03-05"],
        "qty": ["10", "20", "x", "40", "50", "60"],
    }
)

PIPELINE: list[dict[str, Any]] = [
    {"step_type": "trim_strings", "config": {"columns": ["region"]}},
    {"step_type": "fill_nulls", "config": {"strategy": "constant", "columns": ["amount"], "constant_value": 0}},
    {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_or_equal", "value": 10}]}},
    {"step_type": "derive_column", "config": {"target_column": "double", "formula": "[amount] * 2"}},
    {"step_type": "rename_columns", "config": {"mappings": {"region": "market"}}},
    {"step_type": "sort_rows", "config": {"columns": ["amount"], "ascending": False}},
    {"step_type": "limit_rows", "config": {"count": 4}},
]


def _oracle(frame: pd.DataFrame, steps: list[dict[str, Any]]) -> pd.DataFrame:
    """The original handlers, applied in order -- the reference the IR is held to."""
    working = frame.copy()
    for step in validate_steps_json(steps):
        working, _ = STEP_APPLY_FUNCTIONS[step.step_type](working, step.config)
    return working.reset_index(drop=True)


def _same(left: pd.DataFrame, right: pd.DataFrame) -> None:
    assert list(left.columns) == list(right.columns)
    normalised_left = left.astype("object").where(left.notna(), None).reset_index(drop=True)
    normalised_right = right.astype("object").where(right.notna(), None).reset_index(drop=True)
    pd.testing.assert_frame_equal(normalised_left, normalised_right, check_dtype=False)


def test_a_whole_pipeline_matches_the_original_handlers():
    through_ir, warnings, outcomes = apply_transformation_steps_with_outcomes(FRAME, PIPELINE)
    _same(through_ir, _oracle(FRAME, PIPELINE))
    assert [o.step_type for o in outcomes] == [s["step_type"] for s in PIPELINE]
    assert outcomes[2].rows_before == 6 and outcomes[2].rows_after == 5  # the filter
    assert outcomes[-1].rows_after == 4  # the limit
    assert warnings == []


@pytest.mark.parametrize("step_type", sorted(EXTENSION_BACKED - {"join_datasets", "union_datasets"}))
def test_reshaping_steps_still_run_as_extensions(step_type: str):
    configs = {
        "split_column": {"column": "when", "delimiter": "-", "into": ["y", "m", "d"]},
        "pivot": {"index": ["region"], "columns": "label", "values": "amount", "aggregation": "sum"},
        "unpivot": {"id_columns": ["id"], "value_columns": ["amount", "qty"], "variable_column_name": "k", "value_column_name": "v"},
    }
    step = validate_steps_json([{"step_type": step_type, "config": configs[step_type]}])[0]
    through_ir, _ = apply_single_step(FRAME, step)
    expected, _ = STEP_APPLY_FUNCTIONS[step_type](FRAME.copy(), configs[step_type])
    _same(through_ir, expected.reset_index(drop=True))


def test_original_warnings_survive_the_cutover():
    # The legacy `expression` syntax is an Extension path (only formulas compile
    # to IR); its handler warns when the expression names no column, and that
    # warning must still reach the person after the cutover.
    step = validate_steps_json(
        [{"step_type": "derive_column", "config": {"target_column": "one", "expression": "1"}}]
    )[0]
    frame, warnings = apply_single_step(FRAME, step)
    assert list(frame["one"].unique()) == [1]
    assert any("references no columns" in message for message in warnings)


def test_a_step_that_leaves_no_rows_says_so():
    step = validate_steps_json([{"step_type": "limit_rows", "config": {"count": 5, "offset": 50}}])[0]
    frame, warnings = apply_single_step(FRAME, step)
    assert frame.empty
    assert any("no rows" in message for message in warnings)


def test_a_lossy_native_step_warns_about_the_empty_values_it_left_behind():
    step = validate_steps_json(
        [{"step_type": "cast_column_types", "config": {"mappings": {"qty": "int"}}}]
    )[0]
    frame, warnings = apply_single_step(FRAME, step)
    assert frame["qty"].isna().sum() == 1  # "x"
    assert any("qty" in message and "more empty value" in message for message in warnings)


def test_configuration_mistakes_keep_their_field_naming_messages():
    with pytest.raises(BadRequestError, match="config.columns"):
        apply_transformation_steps(FRAME, [{"step_type": "select_columns", "config": {"columns": []}}])
    with pytest.raises(BadRequestError):
        apply_transformation_steps(FRAME, [{"step_type": "drop_columns", "config": {"columns": ["nope"]}}])


def test_join_and_union_reach_the_sibling_dataset_through_the_context():
    right = pd.DataFrame({"region": ["eu", "us"], "manager": ["ann", "bo"]})
    context = StepContext(resolve_dataset=lambda _id: right.copy(), describe_dataset=lambda _id: "regions")
    trimmed = validate_steps_json([{"step_type": "trim_strings", "config": {"columns": ["region"]}}])[0]
    base, _ = apply_single_step(FRAME, trimmed)

    right_id = "11111111-2222-4333-8444-555555555555"
    join = validate_steps_json([{
        "step_type": "join_datasets",
        "config": {"right_dataset_id": right_id, "left_on": ["region"], "right_on": ["region"], "how": "inner"},
    }])[0]
    joined, warnings = apply_single_step(base, join, context)
    expected, expected_warnings = STEP_APPLY_FUNCTIONS_CONTEXT["join_datasets"](base.copy(), join.config, context)
    _same(joined, expected.reset_index(drop=True))
    assert warnings == expected_warnings and any("dropped" in w for w in warnings)

    union = validate_steps_json([{
        "step_type": "union_datasets",
        "config": {"other_dataset_id": right_id, "column_strategy": "union"},
    }])[0]
    unioned, warnings = apply_single_step(base, union, context)
    assert len(unioned) == len(base) + 2
    assert any("different columns" in w for w in warnings)


def test_tools_keep_their_own_warnings():
    step = validate_steps_json(
        [{"step_type": "tool", "config": {"tool": "type.to_number", "column": "qty"}}]
    )[0]
    frame, warnings = apply_single_step(FRAME, step)
    assert frame["qty"].isna().sum() == 1
    assert any("could not read" in w for w in warnings)


def test_an_unknown_step_type_is_refused_plainly():
    step = TransformationStep(step_type="teleport", config={})
    with pytest.raises(BadRequestError, match="Unsupported transformation step"):
        apply_single_step(FRAME, step)


from service_transformations.steps import CONTEXT_STEP_APPLY_FUNCTIONS as STEP_APPLY_FUNCTIONS_CONTEXT  # noqa: E402
