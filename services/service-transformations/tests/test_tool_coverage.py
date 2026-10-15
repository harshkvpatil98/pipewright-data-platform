"""Every entry of the roadmap's tool list is done by something real (E1, T7).

Reads the list from `docs/roadmap-v2.md` itself, so an entry added there and
not here, or a name changed in one place only, fails.
"""

from __future__ import annotations

import pathlib
import re

import pandas as pd
import pytest

from service_transformations.executor import (
    CONTEXT_STEP_APPLY_FUNCTIONS,
    STEP_APPLY_FUNCTIONS,
    apply_transformation_steps,
)
from service_transformations.steps.context import StepContext
from service_transformations.tools import TOOLS
from service_transformations.tools.coverage import FAMILIES, OTHER_DATASET, Done, entries

ROOT = pathlib.Path(__file__).resolve().parents[3]

SAMPLE = pd.DataFrame({
    "id": [1, 2, 3, 4],
    "region": ["eu", "us", "eu", None],
    "amount": [10.0, None, 30.0, 40.0],
    "weight": [1.0, 2.0, 3.0, 4.0],
    "name": [" Ana ", "bo", "Cy", "bo"],
    "when": ["2026-01-01", "2026-01-02", "2026-02-01", "2026-03-01"],
    "paid": [True, False, True, None],
})
OTHER = pd.DataFrame({
    "id": [1, 3, 5, 6], "region": ["eu", "eu", "us", "us"], "amount": [1.0, 2.0, 3.0, 4.0],
    "weight": [1.0, 1.0, 1.0, 1.0], "name": ["x", "y", "z", "w"], "when": ["2026-04-01"] * 4,
    "paid": [True, True, False, False],
})


def _roadmap() -> dict[str, list[str]]:
    text = (ROOT / "docs" / "roadmap-v2.md").read_text(encoding="utf-8")
    block = text[text.index("### Column structure ("):text.index("**Total ≈ 420 tools.**")]
    families: dict[str, list[str]] = {}
    for part in re.split(r"^### ", block, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        body = re.sub(r"^>.*$", "", body, flags=re.M)
        name = re.match(r"(.*) \(\d+\)", head).group(1)
        families[name] = [entry.strip() for entry in " ".join(body.split()).split("·") if entry.strip()]
    return families


def test_every_family_and_every_entry_is_here_once() -> None:
    roadmap = _roadmap()
    assert list(FAMILIES) == list(roadmap)
    for family, listed in roadmap.items():
        here = [done.entry for done in FAMILIES[family]]
        assert len(here) == len(set(here)), f"{family}: an entry is here twice"
        assert sorted(here) == sorted(listed), (
            f"{family}: missing {sorted(set(listed) - set(here))}, not in the roadmap {sorted(set(here) - set(listed))}")
    assert sum(len(items) for items in roadmap.values()) == 447 == len(entries())


@pytest.mark.parametrize(("family", "done"), [item for item in entries() if item[1].by == "tool"],
                         ids=lambda value: value.entry if isinstance(value, Done) else value)
def test_a_tool_entry_names_tools_that_exist(family: str, done: Done) -> None:
    assert done.tools, done.entry
    missing = [name for name in done.tools if name not in TOOLS]
    assert not missing, f"{family} / {done.entry}: no tool called {missing}"


@pytest.mark.parametrize(("family", "done"), [item for item in entries() if item[1].by == "step"],
                         ids=lambda value: value.entry if isinstance(value, Done) else value)
def test_a_step_entry_runs_with_the_setting_it_names(family: str, done: Done) -> None:
    assert done.step in STEP_APPLY_FUNCTIONS or done.step in CONTEXT_STEP_APPLY_FUNCTIONS, done.step
    context = StepContext(resolve_dataset=lambda dataset_id: OTHER.copy() if str(dataset_id) == OTHER_DATASET
                          else None, describe_dataset=lambda _id: "Other")
    out, _ = apply_transformation_steps(SAMPLE.copy(), [{"step_type": done.step, "config": done.config}], context)
    assert isinstance(out, pd.DataFrame) and len(out.columns) > 0, f"{family} / {done.entry}"


def _has_test(reference: str) -> bool:
    path, _, name = reference.partition("::")
    file = ROOT / path
    if not name or not file.is_file():
        return False
    text = file.read_text(encoding="utf-8")
    if file.suffix == ".py":
        return re.search(rf"def {re.escape(name)}\(", text) is not None
    return f'it("{name}"' in text or f"it('{name}'" in text


@pytest.mark.parametrize(("family", "done"), [item for item in entries() if item[1].by == "feature"],
                         ids=lambda value: value.entry if isinstance(value, Done) else value)
def test_a_feature_entry_has_its_test_where_it_says(family: str, done: Done) -> None:
    assert done.how, done.entry
    assert _has_test(done.test), f"{family} / {done.entry}: no test at {done.test}"


def test_only_the_plugin_waits_on_a_later_phase() -> None:
    waiting = [done.entry for _, done in entries() if done.by == "later"]
    assert waiting == ["custom-plugin (Phase 23)"]
    assert all(done.by in ("tool", "step", "feature", "later") for _, done in entries())
