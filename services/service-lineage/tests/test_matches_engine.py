"""Lineage must predict what the engine actually does.

Column lineage is a second implementation of every step's column behaviour. A
second implementation drifts unless something forces the two together, so these
tests run each pipeline for real and assert the predicted column list equals the
frame the transformation engine produced. When one of these fails, lineage is
lying to users about where their data came from.
"""

from __future__ import annotations

import pandas as pd
import pytest
from service_transformations.steps import (
    CONTEXT_STEP_APPLY_FUNCTIONS,
    STEP_APPLY_FUNCTIONS,
    StepContext,
)

from service_lineage.columns import build_pipeline_lineage

SIDE_DATASET_ID = "99999999-9999-9999-9999-999999999999"

SIDE_FRAME = pd.DataFrame(
    {
        "id": [1, 2, 3],
        "name": ["north", "south", "east"],
        "tier": ["gold", "silver", "bronze"],
    }
)


def _run(frame: pd.DataFrame, steps: list[dict]) -> pd.DataFrame:
    context = StepContext(
        resolve_dataset=lambda dataset_id: SIDE_FRAME.copy(),
        describe_dataset=lambda dataset_id: "side dataset",
    )
    working = frame
    for step in steps:
        step_type, config = step["step_type"], step["config"]
        if step_type in STEP_APPLY_FUNCTIONS:
            working, _ = STEP_APPLY_FUNCTIONS[step_type](working, config)
        else:
            working, _ = CONTEXT_STEP_APPLY_FUNCTIONS[step_type](working, config, context)
    return working


BASE = pd.DataFrame(
    {
        "id": [1, 2, 3, 3],
        "name": ["ann lee", "bo ray", "cy fox", "cy fox"],
        "region": ["north", "south", "east", "east"],
        "amount": [10.0, 20.0, 30.0, 30.0],
    }
)


CASES: list[tuple[str, list[dict]]] = [
    (
        "rename then cast",
        [
            {"step_type": "rename_columns", "config": {"mappings": {"amount": "revenue"}}},
            {"step_type": "cast_column_types", "config": {"mappings": {"revenue": "float"}}},
        ],
    ),
    (
        "split and drop the original",
        [
            {
                "step_type": "split_column",
                "config": {"column": "name", "delimiter": " ", "into": ["first", "last"], "drop_original": True},
            }
        ],
    ),
    (
        "split and keep the original",
        [
            {
                "step_type": "split_column",
                "config": {"column": "name", "delimiter": " ", "into": ["first", "last"]},
            }
        ],
    ),
    (
        "derive a column",
        [{"step_type": "derive_column", "config": {"target_column": "net", "expression": "amount * 0.8"}}],
    ),
    (
        "derive over an existing column",
        [
            {
                "step_type": "derive_column",
                "config": {"target_column": "amount", "expression": "amount * 2", "overwrite": True},
            }
        ],
    ),
    (
        "select a subset in a new order",
        [{"step_type": "select_columns", "config": {"columns": ["region", "id"]}}],
    ),
    (
        "drop a column",
        [{"step_type": "drop_columns", "config": {"columns": ["name"]}}],
    ),
    (
        "group and aggregate",
        [
            {
                "step_type": "aggregate",
                "config": {
                    "group_by": ["region"],
                    "aggregations": [
                        {"column": "amount", "function": "sum", "alias": "total"},
                        {"column": "id", "function": "count"},
                    ],
                },
            }
        ],
    ),
    (
        "unpivot with explicit names",
        [
            {
                "step_type": "unpivot",
                "config": {
                    "id_columns": ["id"],
                    "value_columns": ["region", "name"],
                    "variable_column_name": "field",
                    "value_column_name": "content",
                },
            }
        ],
    ),
    (
        "unpivot defaulting the value columns",
        [{"step_type": "unpivot", "config": {"id_columns": ["id", "name"]}}],
    ),
    (
        "row steps leave columns alone",
        [
            {"step_type": "remove_duplicates", "config": {}},
            {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 5}]}},
            {"step_type": "sort_rows", "config": {"columns": ["amount"]}},
            {"step_type": "limit_rows", "config": {"count": 2}},
        ],
    ),
    (
        "join taking selected right columns",
        [
            {
                "step_type": "join_datasets",
                "config": {
                    "right_dataset_id": SIDE_DATASET_ID,
                    "left_on": ["id"],
                    "right_on": ["id"],
                    "select_right_columns": ["tier"],
                },
            }
        ],
    ),
    (
        "join taking every right column, including a colliding name",
        [
            {
                "step_type": "join_datasets",
                "config": {
                    "right_dataset_id": SIDE_DATASET_ID,
                    "left_on": ["id"],
                    "right_on": ["id"],
                },
            }
        ],
    ),
    (
        "union adding a column",
        [{"step_type": "union_datasets", "config": {"other_dataset_id": SIDE_DATASET_ID}}],
    ),
    (
        "union intersecting columns",
        [
            {
                "step_type": "union_datasets",
                "config": {"other_dataset_id": SIDE_DATASET_ID, "column_strategy": "intersect"},
            }
        ],
    ),
    (
        "a realistic chain",
        [
            {"step_type": "remove_duplicates", "config": {}},
            {"step_type": "rename_columns", "config": {"mappings": {"amount": "revenue"}}},
            {"step_type": "derive_column", "config": {"target_column": "net", "expression": "revenue * 0.8"}},
            {"step_type": "drop_columns", "config": {"columns": ["name"]}},
            {
                "step_type": "aggregate",
                "config": {
                    "group_by": ["region"],
                    "aggregations": [{"column": "net", "function": "sum", "alias": "net_total"}],
                },
            },
            {"step_type": "sort_rows", "config": {"columns": ["net_total"], "ascending": False}},
        ],
    ),
]


@pytest.mark.parametrize("label,steps", CASES, ids=[case[0] for case in CASES])
def test_predicted_columns_match_a_real_run(label: str, steps: list[dict]):
    actual = _run(BASE.copy(), steps)
    predicted = build_pipeline_lineage(
        base_columns=list(BASE.columns),
        steps=steps,
        resolve_schema=lambda dataset_id: list(SIDE_FRAME.columns),
    )
    assert predicted.output_columns == [str(column) for column in actual.columns], label


def test_pivot_predicts_the_index_columns_and_admits_the_rest_is_data():
    steps = [
        {
            "step_type": "pivot",
            "config": {"index": ["region"], "columns": "id", "values": "amount", "aggregation": "sum"},
        }
    ]
    actual = _run(BASE.copy(), steps)
    predicted = build_pipeline_lineage(base_columns=list(BASE.columns), steps=steps)

    # The index column is predictable; the generated ones are whatever the data held.
    assert predicted.output_columns[0] == "region"
    assert str(actual.columns[0]) == "region"
    assert predicted.dynamic is True
    assert len(actual.columns) > 1
