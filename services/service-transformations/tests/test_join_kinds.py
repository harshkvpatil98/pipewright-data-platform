"""The join step's full, cross, semi and anti joins (E1).

Semi and anti joins keep this dataset's rows by whether another dataset has a
match, never repeating a row and never bringing a column; an empty key
matches nothing, as in SQL. A cross join pairs every row with every row and
is counted before it is built, like any join.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext

LEFT = pd.DataFrame({"id": [1, 2, 3, None], "name": ["a", "b", "c", "d"]})
RIGHT = pd.DataFrame({"id": [1, 1, 3, None], "colour": ["red", "blue", "green", "grey"]})
OTHER = "00000000-0000-0000-0000-000000000001"


def run(how: str, **extra) -> tuple[pd.DataFrame, list[str]]:
    config = {"right_dataset_id": OTHER, "how": how, **extra}
    if how != "cross":
        config.setdefault("left_on", ["id"])
        config.setdefault("right_on", ["id"])
    context = StepContext(resolve_dataset=lambda _id: RIGHT.copy(), describe_dataset=lambda _id: "Colours")
    return apply_transformation_steps(LEFT, [{"step_type": "join_datasets", "config": config}], context)


def test_a_semi_join_keeps_matching_rows_once_without_their_columns() -> None:
    out, _ = run("semi")
    assert out["name"].tolist() == ["a", "c"]
    assert list(out.columns) == ["id", "name"]


def test_an_anti_join_keeps_the_rest_including_an_empty_key() -> None:
    out, _ = run("anti")
    assert out["name"].tolist() == ["b", "d"]


def test_a_semi_join_that_matches_nothing_says_so() -> None:
    _, warnings = run("semi", left_on=["name"], right_on=["colour"])
    assert any("No rows matched 'Colours'" in w for w in warnings)


def test_a_cross_join_pairs_every_row_and_suffixes_clashes() -> None:
    out, _ = run("cross")
    assert len(out) == 16
    assert list(out.columns) == ["id", "name", "id_right", "colour"]


def test_a_cross_join_takes_no_keys() -> None:
    with pytest.raises(BadRequestError, match="matches on no columns"):
        run("cross", left_on=["id"], right_on=["id"])


def test_full_is_another_word_for_outer() -> None:
    full, _ = run("full")
    outer, _ = run("outer")
    pd.testing.assert_frame_equal(full, outer)


@pytest.mark.parametrize("how", ["semi", "anti", "cross"])
def test_lineage_says_what_each_gives(how: str) -> None:
    from service_lineage.columns import build_pipeline_lineage

    config = {"right_dataset_id": OTHER, "how": how}
    if how != "cross":
        config.update(left_on=["id"], right_on=["id"])
    lineage = build_pipeline_lineage(base_columns=list(LEFT.columns),
                                     steps=[{"step_type": "join_datasets", "config": config}],
                                     resolve_schema=lambda _id: {"id": None, "colour": None})
    expected = ["id", "name"] if how != "cross" else ["id", "name", "id_right", "colour"]
    assert lineage.steps[-1].output_columns == expected


def test_the_ir_join_agrees_with_the_step_on_a_semi_join() -> None:
    from service_transformations.executor import scan_of
    from service_transformations.ir.from_steps import compile_step
    from service_transformations.ir.pandas_backend import execute

    right_scan = scan_of(RIGHT, "colours")
    node = compile_step(scan_of(LEFT, "left"), "join_datasets", {
        "right_dataset_id": OTHER, "how": "semi", "left_on": ["id"], "right_on": ["id"], "_right_node": right_scan})
    out = execute(node, {"left": LEFT, "colours": RIGHT})
    assert out["name"].tolist() == run("semi")[0]["name"].tolist()
