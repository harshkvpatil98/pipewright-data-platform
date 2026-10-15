"""Recipes that compute only what changed give what a full run gives (D2, O7).

An import reads a SQLite table into a dataset, each run a new version of it.
Two recipes with the same steps read that dataset: one computes only what
changed, one always runs in full. After every change to the table (rows
added at the end, a row changed, one partition's rows changed) both run, and
their results must hold the same rows and values. The incremental one must
also have done less, and said what; or run in full and said why.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_extraction.extract import run_extraction_job
from service_extraction.models import ExtractionConnection, ExtractionJob
from service_pipeline_runs.models import PipelineRun
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.prefix_cache import CACHE
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import IncrementalSettings, TransformationPipelineCreate
from service_transformations.service import create_transformation_pipeline, set_incremental
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

SETTINGS = SimpleNamespace(max_upload_size_bytes=200 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)
RNG = np.random.default_rng(9)
REGIONS = ["north", "south", "east", "west"]


def _rows(start: int, count: int) -> list[tuple]:
    return [(i, REGIONS[i % 4], round(float(RNG.gamma(2.0, 20.0)), 2), f"2026-0{1 + i % 9}-1{i % 10}",
             None if i % 7 == 0 else f"  note {i % 5}  ") for i in range(start, start + count)]


@pytest.fixture(autouse=True)
def _fresh_cache():
    CACHE.clear()
    yield
    CACHE.clear()


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def world(db: Session, tmp_path) -> dict:
    source = str(tmp_path / "shop.db")
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, amount REAL, placed_on TEXT, note TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", _rows(0, 2_000))
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    connection = ExtractionConnection(project_id=project.id, name="Shop DB", connector_type="sqlite",
                                      config_json={"file_path": source})
    db.add(connection)
    db.flush()
    job = ExtractionJob(project_id=project.id, connection_id=connection.id, name="Orders", source_kind="table",
                        source_table="orders", load_mode="full_refresh")
    db.add(job)
    db.commit()
    world = {"project": project, "user": user, "job": job, "source": source,
             "storage": LocalStorageBackend(str(tmp_path / "storage"))}
    world["dataset_id"] = _import(db, world)
    return world


def _import(db: Session, world: dict):
    result = run_extraction_job(db, project_id=world["project"].id, job_id=world["job"].id, current_user=world["user"],
                                storage_backend=world["storage"], settings=SETTINGS)
    return result.dataset_id


def _recipe(db: Session, world: dict, name: str, steps: list[dict], mode: str = "full", column: str | None = None):
    recipe = create_transformation_pipeline(
        db, project_id=world["project"].id, dataset_id=world["dataset_id"],
        payload=TransformationPipelineCreate(name=name, steps_json=steps), current_user=world["user"])
    if mode != "full":
        set_incremental(db, project_id=world["project"].id, pipeline_id=recipe.id,
                        settings=IncrementalSettings(mode=mode, partition_column=column), current_user=world["user"])
    return recipe.id


def _run(db: Session, world: dict, recipe_id) -> tuple[pd.DataFrame, list[str]]:
    CACHE.clear()  # a kept result would make the full recipe cheap too, and prove nothing
    result = run_saved_transformation_pipeline(db, project_id=world["project"].id, pipeline_id=recipe_id,
                                               current_user=world["user"], storage_backend=world["storage"],
                                               settings=SETTINGS)
    dataset = db.get(Dataset, result.dataset.id)
    frame = pd.read_csv(world["storage"].root_path / dataset.file_path) if hasattr(world["storage"], "root_path") \
        else pd.read_csv(pd.io.common.BytesIO(world["storage"].read_bytes(dataset.file_path)))
    run = db.get(PipelineRun, result.run.id)
    events = [event for event in (run.logs_json or {}).get("events", []) if event.get("stage") == "incremental"]
    world["read"] = [(event.get("details") or {}).get("read") for event in events]
    return frame, [event["message"] for event in events]


def _same(a: pd.DataFrame, b: pd.DataFrame, *, ordered: bool) -> None:
    assert list(a.columns) == list(b.columns)
    if not ordered:
        a = a.sort_values(list(a.columns)).reset_index(drop=True)
        b = b.sort_values(list(b.columns)).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


ROW_BY_ROW = [
    {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 10}]}},
    {"step_type": "trim_strings", "config": {"columns": ["note"]}},
    {"step_type": "fill_nulls", "config": {"strategy": "constant", "columns": ["note"], "constant_value": "none"}},
    {"step_type": "derive_column", "config": {"target_column": "doubled", "formula": "[amount] * 2"}},
    {"step_type": "parse_dates", "config": {"columns": ["placed_on"]}},
    {"step_type": "rename_columns", "config": {"mappings": {"region": "market"}}},
]


def _append(world: dict, start: int, count: int) -> None:
    with sqlite3.connect(world["source"]) as conn:
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", _rows(start, count))


def test_rows_added_at_the_end_are_all_that_is_computed(db: Session, world: dict) -> None:
    quick = _recipe(db, world, "Only new rows", ROW_BY_ROW, mode="append")
    whole = _recipe(db, world, "Every row", ROW_BY_ROW)
    first, said = _run(db, world, quick)
    assert said == ["Ran in full: there is no earlier run of this recipe to build on."]
    _same(first, _run(db, world, whole)[0], ordered=True)

    _append(world, 2_000, 500)
    _import(db, world)
    # PostgreSQL keeps a JSON column's keys in an order of its own (shortest first): the record of
    # how the input read must still match, as it did not when it was compared in order.
    last = db.query(PipelineRun).filter(PipelineRun.pipeline_id == quick).order_by(PipelineRun.created_at.desc()).first()
    kinds = last.summary_json["input_kinds"]
    last.summary_json = {**last.summary_json, "input_kinds": dict(sorted(kinds.items(), key=lambda kv: (len(kv[0]), kv[0])))}
    db.commit()
    second, said = _run(db, world, quick)
    assert said == ["Computed only the 500 rows added since the last run, and kept the "
                    f"{len(first):,} rows it made."]
    assert world["read"] == ["the new rows only"]  # the file the last run read is the start of this one
    _same(second, _run(db, world, whole)[0], ordered=True)

    # Nothing new: the last result, as it was.
    _import(db, world)
    third, said = _run(db, world, quick)
    assert said == ["The input has not changed since the last run, so its result was kept as it was."]
    _same(third, second, ordered=True)


def test_a_row_that_changed_sends_the_run_back_to_every_row(db: Session, world: dict) -> None:
    quick = _recipe(db, world, "Only new rows", ROW_BY_ROW, mode="append")
    whole = _recipe(db, world, "Every row", ROW_BY_ROW)
    _run(db, world, quick)
    with sqlite3.connect(world["source"]) as conn:
        conn.execute("UPDATE orders SET amount = 999 WHERE id = 5")
    _append(world, 2_000, 10)
    _import(db, world)
    again, said = _run(db, world, quick)
    assert said == ["Ran in full: rows the last run read have changed, not only new rows added after them."]
    _same(again, _run(db, world, whole)[0], ordered=True)


def test_only_the_partitions_whose_rows_changed_are_computed_again(db: Session, world: dict) -> None:
    steps = [
        *ROW_BY_ROW[:2],
        {"step_type": "aggregate", "config": {"group_by": ["region", "placed_on"],
                                              "aggregations": [{"column": "amount", "function": "sum"},
                                                               {"column": "id", "function": "count"}]}},
    ]
    quick = _recipe(db, world, "Changed regions", steps, mode="partition", column="region")
    whole = _recipe(db, world, "Every region", steps)
    _run(db, world, quick)
    with sqlite3.connect(world["source"]) as conn:
        conn.execute("UPDATE orders SET amount = amount + 1 WHERE region = 'north'")
        conn.execute("DELETE FROM orders WHERE region = 'east' AND id % 3 = 0")
    _import(db, world)
    again, said = _run(db, world, quick)
    assert said and said[0].startswith("Computed again only the 2 partitions of region whose rows changed (east and north)")
    _same(again, _run(db, world, whole)[0], ordered=False)


@pytest.mark.parametrize(("step", "reason"), [
    ({"step_type": "sort_rows", "config": {"columns": ["amount"]}}, "step 1 (Sort rows) puts every row in order"),
    ({"step_type": "remove_duplicates", "config": {"subset": ["region"]}}, "removes repeated rows across all of them"),
    ({"step_type": "derive_column", "config": {"target_column": "seen", "formula": "TODAY()"}}, "reads the clock"),
    ({"step_type": "fill_nulls", "config": {"strategy": "mean", "columns": ["amount"]}}, "fills empty values from other rows"),
])
def test_a_step_that_needs_every_row_runs_in_full_and_says_which(db: Session, world: dict, step: dict, reason: str) -> None:
    recipe = _recipe(db, world, "Needs every row", [step], mode="append")
    _run(db, world, recipe)
    _append(world, 2_000, 5)
    _import(db, world)
    _frame, said = _run(db, world, recipe)
    assert len(said) == 1 and said[0].startswith("Ran in full:") and reason in said[0]


def test_changing_the_steps_runs_in_full(db: Session, world: dict) -> None:
    from service_transformations.schemas import TransformationPipelineUpdate
    from service_transformations.service import update_transformation_pipeline

    recipe = _recipe(db, world, "Only new rows", ROW_BY_ROW, mode="append")
    _run(db, world, recipe)
    update_transformation_pipeline(db, project_id=world["project"].id, pipeline_id=recipe,
                                   payload=TransformationPipelineUpdate(steps_json=ROW_BY_ROW[:3]),
                                   current_user=world["user"])
    _append(world, 2_000, 5)
    _import(db, world)
    assert _run(db, world, recipe)[1] == ["Ran in full: the recipe's steps changed since the last run."]


def test_a_run_reuses_what_a_preview_kept_and_the_other_way_round(db: Session, world: dict) -> None:
    """A preview and a run of the same steps over the same version share what they keep. A run
    once stopped with a KeyError on the input a preview had kept, which it described differently."""
    from service_transformations.preview import preview_dataset_transformations
    from service_transformations.schemas import TransformationPreviewRequest

    recipe = _recipe(db, world, "Shared", ROW_BY_ROW)

    def preview():
        return preview_dataset_transformations(
            db, project_id=world["project"].id, dataset_id=world["dataset_id"],
            payload=TransformationPreviewRequest(steps=ROW_BY_ROW), current_user=world["user"],
            storage_backend=world["storage"], settings=SETTINGS)

    CACHE.clear()
    shown = preview()
    result = run_saved_transformation_pipeline(db, project_id=world["project"].id, pipeline_id=recipe,
                                               current_user=world["user"], storage_backend=world["storage"],
                                               settings=SETTINGS)
    run = db.get(PipelineRun, result.run.id)
    reused = [e["message"] for e in run.logs_json["events"] if e.get("stage") == "reused"]
    assert reused and "from a recent preview or run" in reused[0]
    assert result.dataset.row_count == shown.row_count_after
    assert run.summary_json["input_kinds"]  # kept for the next incremental run, reused or not
    again = preview()  # and back the other way: the run's kept input serves a preview
    assert again.row_count_before == shown.row_count_before and again.row_count_after == shown.row_count_after
