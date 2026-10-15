"""The recipe merge rules (C2), held to the fixtures the Studio shares.

Each case is merged in the order given, reversed and shuffled, and must
come out the same every time: that is what lets people's changes arrive in
any order. Positions always fall strictly between their neighbours.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from service_transformations.coedit import apply_ops, between, empty_doc, materialise, seed

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "features" / "studio" / "coedit-fixtures.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURES["between"], ids=lambda case: f"{case['low']}-{case['high']}")
def test_positions_match_the_studios(case) -> None:
    assert between(case["low"], case["high"]) == case["expect"]


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["name"])
def test_every_order_merges_the_same(case) -> None:
    orders = [case["ops"], list(reversed(case["ops"]))]
    shuffler = random.Random(case["name"])
    for _ in range(20):
        shuffled = list(case["ops"])
        shuffler.shuffle(shuffled)
        orders.append(shuffled)
    for ops in orders:
        assert materialise(apply_ops(empty_doc(), ops)) == case["expect"]
    # Merging the same changes twice changes nothing.
    assert materialise(apply_ops(empty_doc(), case["ops"] + case["ops"])) == case["expect"]


def test_a_position_is_always_strictly_between() -> None:
    chooser = random.Random(7)
    positions = [between(None, None)]
    for _ in range(2000):
        positions.sort()
        index = chooser.randrange(len(positions) + 1)
        low = positions[index - 1] if index > 0 else None
        high = positions[index] if index < len(positions) else None
        made = between(low, high)
        assert (low is None or low < made) and (high is None or made < high)
        assert not made.endswith("0")
        positions.append(made)
    assert len(set(positions)) == len(positions)


def test_a_seeded_copy_is_the_saved_recipe() -> None:
    steps = [{"step_type": "drop_columns", "config": {"columns": ["a"]}}, {"step_type": "sort_rows", "config": {}}]
    doc = seed("Clean orders", steps, ["s1", "s2"])
    assert materialise(doc) == {
        "name": "Clean orders",
        "steps": [
            {"id": "s1", "step_type": "drop_columns", "config": {"columns": ["a"]}},
            {"id": "s2", "step_type": "sort_rows", "config": {}},
        ],
    }


def test_a_recipe_change_is_described_in_words() -> None:
    """The generic diff said "Added steps json[step type=sort rows]" (C2)."""
    from service_transformations.versioning import describe_recipe_change

    dedupe = {"step_type": "remove_duplicates", "config": {}}
    sort = {"step_type": "sort_rows", "config": {"columns": ["amount"]}}
    drop = {"step_type": "drop_columns", "config": {"columns": ["a"]}}
    assert describe_recipe_change({"name": "A", "steps_json": [dedupe]}, {"name": "A", "steps_json": [dedupe, sort]}) == (
        "Adds a sort rows step (step 2)."
    )
    assert describe_recipe_change(
        {"name": "A", "steps_json": [drop, dedupe]},
        {"name": "B", "steps_json": [dedupe, {"step_type": "drop_columns", "config": {"columns": ["b"]}}]},
    ) == "Renames it to “B”. Changes the drop columns step (step 2)."
    assert describe_recipe_change({"name": "A", "steps_json": [dedupe, sort]}, {"name": "A", "steps_json": [sort, dedupe]}) == (
        "Moves the sort rows step from step 2 to step 1."
    )
    assert describe_recipe_change(None, {"name": "A", "steps_json": []}) == "Created."
