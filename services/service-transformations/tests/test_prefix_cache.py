"""What a recipe's first steps made is kept and reused (D2, O6).

Changing step 14 of 15 runs steps 14 and 15; running the same steps again
runs none; and the result is the one a full run gives, value for value. A
step that reads the clock is never kept, nor anything after it. Kept frames
are shared between steps, so no step type may change its input in place:
`test_no_step_changes_the_frame_it_is_given` holds every one of them to it.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from service_transformations.executor import apply_single_step, validate_steps_json
from service_transformations.prefix_cache import CACHE, PrefixCache, Kept, run_steps
from service_transformations.steps import ALL_STEP_TYPES
from service_transformations.steps.context import StepContext

RNG = np.random.default_rng(14)
N = 5_000
FRAME = pd.DataFrame({
    "order_id": np.arange(N),
    "customer": RNG.choice([f" Customer {i} " for i in range(300)], N),
    "region": RNG.choice(["north", "south", "east", "west", None], N),
    "amount": RNG.normal(100, 30, N).round(2),
    "qty": RNG.integers(1, 9, N),
    "status": RNG.choice(["paid", "refunded", "open"], N),
})
STEPS = [
    {"step_type": "trim_strings", "config": {"columns": ["customer"]}},
    {"step_type": "fill_nulls", "config": {"strategy": "constant", "columns": ["region"], "constant_value": "unknown"}},
    {"step_type": "derive_column", "config": {"target_column": "total", "formula": "[amount] * [qty]"}},
    {"step_type": "filter_rows", "config": {"conditions": [{"column": "status", "operator": "equals", "value": "paid"}]}},
    {"step_type": "rename_columns", "config": {"mappings": {"region": "market"}}},
    {"step_type": "sort_rows", "config": {"columns": ["total"], "ascending": False}},
    {"step_type": "limit_rows", "config": {"count": 100}},
]


@pytest.fixture(autouse=True)
def _empty_cache():
    CACHE.clear()
    yield
    CACHE.clear()


class Counting:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.loads = 0

    def load(self) -> pd.DataFrame:
        self.loads += 1
        return FRAME.copy()

    def apply(self, frame: pd.DataFrame, step) -> tuple[pd.DataFrame, list[str]]:
        self.applied.append(step.step_type)
        return apply_single_step(frame, step, None)


def _run(steps, counting: Counting, base: str | None = "orders@v1"):
    return run_steps(base=base, load=counting.load, steps=validate_steps_json(steps), apply=counting.apply)


def _full(steps) -> pd.DataFrame:
    frame = FRAME.copy()
    for step in validate_steps_json(steps):
        frame, _ = apply_single_step(frame, step, None)
    return frame


def test_changing_a_late_step_runs_only_it_and_what_follows() -> None:
    first = Counting()
    ran = _run(STEPS, first)
    assert len(first.applied) == len(STEPS) and first.loads == 1
    pd.testing.assert_frame_equal(ran.frame, _full(STEPS))

    edited = [*STEPS[:-1], {"step_type": "limit_rows", "config": {"count": 10}}]
    second = Counting()
    ran = _run(edited, second)
    assert second.applied == ["limit_rows"] and second.loads == 0
    assert ran.reused_steps == len(STEPS) - 1
    pd.testing.assert_frame_equal(ran.frame, _full(edited))
    # What each step did is still reported, reused or not.
    assert [outcome.index for outcome in ran.outcomes] == list(range(len(STEPS)))
    assert ran.outcomes[3].rows_before == N

    again = Counting()
    assert _run(edited, again).reused_steps == len(STEPS) and again.applied == []


def test_a_different_input_or_nothing_to_address_it_by_keeps_nothing_shared() -> None:
    _run(STEPS, Counting())
    other = Counting()
    _run(STEPS, other, base="orders@v2")
    assert len(other.applied) == len(STEPS) and other.loads == 1
    unaddressed = Counting()
    _run(STEPS, unaddressed, base=None)
    _run(STEPS, unaddressed, base=None)
    assert len(unaddressed.applied) == 2 * len(STEPS)


def test_a_step_that_reads_the_clock_is_never_kept_nor_anything_after_it() -> None:
    steps = [
        STEPS[0],
        {"step_type": "derive_column", "config": {"target_column": "seen", "formula": "TODAY()"}},
        *STEPS[1:3],
    ]
    _run(steps, Counting())
    again = Counting()
    ran = _run(steps, again)
    assert ran.reused_steps == 1  # the trim, kept; the clock step and the rest, run again
    assert again.applied == ["derive_column", "fill_nulls", "derive_column"]


def test_a_join_without_an_address_for_the_other_dataset_is_not_kept() -> None:
    other = pd.DataFrame({"status": ["paid", "open"], "label": ["P", "O"]})
    context = StepContext(resolve_dataset=lambda _id: other.copy(), describe_dataset=lambda _id: "Statuses")
    steps = validate_steps_json([
        STEPS[0],
        {"step_type": "join_datasets", "config": {"right_dataset_id": str(uuid.uuid4()), "left_on": ["status"],
                                                  "right_on": ["status"]}},
        STEPS[1],
    ])
    applied: list[str] = []

    def apply(frame, step):
        applied.append(step.step_type)
        return apply_single_step(frame, step, context)

    for other_of in (None, lambda kind, config: None):
        run_steps(base="orders@v1", load=FRAME.copy, steps=steps, apply=apply, other_of=other_of)
    # The trim is kept; the join and the step after it run every time.
    assert applied == ["trim_strings", "join_datasets", "fill_nulls", "join_datasets", "fill_nulls"]
    applied.clear()
    run_steps(base="orders@v1", load=FRAME.copy, steps=steps, apply=apply, other_of=lambda kind, config: "statuses@v3")
    run_steps(base="orders@v1", load=FRAME.copy, steps=steps, apply=apply, other_of=lambda kind, config: "statuses@v3")
    assert applied == ["join_datasets", "fill_nulls"]  # addressed, so kept the first time


def test_the_store_keeps_to_its_budget_and_its_lifetime(monkeypatch) -> None:
    store = PrefixCache()
    monkeypatch.setenv("RECIPE_CACHE_MB", "1")
    piece = pd.DataFrame({"x": np.arange(50_000)})  # 400 KB
    for name in "abc":
        store.put(name, Kept(frame=piece, outcomes=[], warnings=[], size=400_000))
    assert store.get("a") is None and store.get("b") is not None and store.get("c") is not None
    store.put("huge", Kept(frame=piece, outcomes=[], warnings=[], size=900_000))  # over half the budget
    assert store.get("huge") is None
    monkeypatch.setenv("RECIPE_CACHE_MINUTES", "0")
    assert store.get("b") is None


# Every step type, with settings that do something to FRAME.
EXAMPLES: dict[str, dict] = {
    "rename_columns": {"mappings": {"region": "market"}},
    "cast_column_types": {"mappings": {"qty": "float", "order_id": "string"}},
    "trim_strings": {"columns": ["customer"]},
    "drop_columns": {"columns": ["status"]},
    "select_columns": {"columns": ["order_id", "amount"]},
    "split_column": {"column": "customer", "delimiter": " ", "into": ["word", "number"]},
    "derive_column": {"target_column": "total", "formula": "[amount] * [qty]"},
    "fill_nulls": {"strategy": "constant", "columns": ["region"], "constant_value": "unknown"},
    "drop_null_rows": {"how": "any", "columns": ["region"]},
    "remove_duplicates": {"subset": ["customer"]},
    "replace_values": {"column": "status", "replacements": [{"find": "paid", "replace_with": "settled"}]},
    "parse_dates": {"columns": ["when"]},
    "filter_rows": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 100}]},
    "sort_rows": {"columns": ["amount"], "ascending": False},
    "limit_rows": {"count": 10},
    "aggregate": {"group_by": ["status"], "aggregations": [{"column": "amount", "function": "sum"}]},
    "pivot": {"index": ["region"], "columns": "status", "values": "amount", "aggregation": "sum"},
    "unpivot": {"id_columns": ["order_id"], "value_columns": ["amount", "qty"]},
    "tool": {"tool": "text.trim", "column": "customer"},
    "join_datasets": {"right_dataset_id": str(uuid.uuid4()), "left_on": ["status"], "right_on": ["status"]},
    "union_datasets": {"other_dataset_id": str(uuid.uuid4())},
}


@pytest.mark.parametrize("step_type", sorted(ALL_STEP_TYPES))
def test_no_step_changes_the_frame_it_is_given(step_type: str) -> None:
    assert step_type in EXAMPLES, f"Add an example for {step_type}: kept frames are shared between steps."
    given = FRAME.assign(when=pd.Timestamp("2026-01-01").strftime("%Y-%m-%d"))
    before = given.copy(deep=True)
    other = given.head(20).copy()
    context = StepContext(resolve_dataset=lambda _id: other.copy(), describe_dataset=lambda _id: "Other")
    (step,) = validate_steps_json([{"step_type": step_type, "config": EXAMPLES[step_type]}])
    out, _ = apply_single_step(given, step, context)
    assert out is not given
    pd.testing.assert_frame_equal(given, before)
