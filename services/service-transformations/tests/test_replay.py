"""Deterministic replay (phase-18 §3), against a real database.

The claim under test is narrow and strong: a replay reproduces the recorded
result from the recorded inputs at the recorded instant -- not today's result
from today's data -- and when it cannot, it says which of the four reasons
applies instead of claiming equivalence.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion, DatasetVersionPin
from service_datasets.service import finalize_dataset_materialization_success
from service_datasets.version_lifecycle import prune_due, schedule_prunes
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_pipeline_runs.models import PipelineRun
from service_pipeline_runs.service import get_run_audit_summary
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.execution_context import context_from_run
from service_transformations.ir.clock import frozen_clock
from service_transformations.models import TransformationPipeline
from service_transformations.replay import replay_pipeline_run
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import TransformationPipelineCreate
from service_transformations.service import create_transformation_pipeline
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.storage import content_digest
from shared_python.storage.local import LocalStorageBackend

CSV = b"""customer,born,amount
ann,1990-06-15,10
bo,2000-01-01,20
cy,1985-12-31,
"""

STEPS = [
    {"step_type": "derive_column", "config": {"target_column": "as_of", "formula": "TODAY()"}},
    {"step_type": "derive_column", "config": {"target_column": "age", "formula": "AGE_YEARS([born])"}},
    {
        "step_type": "filter_rows",
        "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 0}]},
    },
]

THEN = datetime(2031, 3, 10, 8, 0, tzinfo=UTC)
MUCH_LATER = THEN + timedelta(days=3650)


@pytest.fixture()
def storage(tmp_path) -> LocalStorageBackend:
    return LocalStorageBackend(str(tmp_path / "storage"))


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
def user(db: Session) -> UserRead:
    row = User(username="runner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    return UserRead(id=row.id, username=row.username, role="admin", is_active=True,
                    created_at=now, updated_at=now)


@pytest.fixture()
def world(db: Session, user: UserRead, storage: LocalStorageBackend) -> dict:
    project = create_project(db, ProjectCreate(name="Replay", description=None), user)
    uploaded = ingest_project_file(
        db, project_id=project.id, dataset_name="people",
        upload_file=IngestionUpload(file_name="people.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    pipeline = create_transformation_pipeline(
        db, project_id=project.id, dataset_id=uploaded.dataset.id,
        payload=TransformationPipelineCreate(name="ages", steps_json=STEPS), current_user=user,
    )
    # The original run, at a known instant.
    with frozen_clock(THEN):
        original = run_saved_transformation_pipeline(
            db, project_id=project.id, pipeline_id=pipeline.id, current_user=user,
            storage_backend=storage, settings=settings, notify_on_complete=False,
        )
    return {
        "project": project, "dataset": uploaded.dataset, "pipeline": pipeline,
        "original": original, "upload_run_id": uploaded.dataset.pipeline_run_id,
    }


def _replay(db, world, user, storage):
    return replay_pipeline_run(
        db, project_id=world["project"].id, run_id=world["original"].run.id,
        current_user=user, storage_backend=storage, settings=settings,
    )


def _rows(dataset) -> dict[str, dict]:
    return {row["customer"]: row for row in dataset.preview_json["rows"]}


def test_a_replay_reproduces_the_recorded_result_not_todays(db, world, user, storage):
    # Time moves on AND the pipeline is edited afterwards: both must be ignored.
    pipeline = db.get(TransformationPipeline, world["pipeline"].id)
    pipeline.steps_json = STEPS[:1]  # somebody removed the age step later
    db.commit()

    with frozen_clock(MUCH_LATER):
        # A fresh run today would give different ages (the control)...
        control = run_saved_transformation_pipeline(
            db, project_id=world["project"].id, pipeline_id=pipeline.id, current_user=user,
            storage_backend=storage, settings=settings, notify_on_complete=False,
        )
        assert "age" not in control.dataset.preview_json["columns"]

        # ...but the replay reproduces the recorded run exactly.
        result = _replay(db, world, user, storage)

    assert result.status == "equivalent", result.reason
    assert result.replay_run_id is not None and result.replay_run_id != world["original"].run.id
    assert result.original_output["version_number"] == 1
    assert result.replay_output["content_hash"] == result.original_output["content_hash"]
    assert result.comparison.method.startswith("content digests are equal")
    assert result.evaluated_at == THEN

    replay_run = db.get(PipelineRun, result.replay_run_id)
    assert replay_run.run_type == "dataset_transformation_replay"
    context = context_from_run(replay_run.summary_json)
    assert context.replay_of == str(world["original"].run.id)
    assert context.evaluated_at == THEN
    assert context.steps == STEPS  # the recorded steps, not the edited pipeline

    replayed = db.get(Dataset, result.replay_dataset_id)
    rows = _rows(replayed)
    assert int(rows["ann"]["age"]) == 40 and str(rows["ann"]["as_of"]).startswith("2031-03-10")
    assert replayed.name.endswith("· replay")

    # Pins were taken for the copy and released afterwards -- none left open.
    pins = db.scalars(select(DatasetVersionPin).where(DatasetVersionPin.holder_kind == "replay")).all()
    assert len(pins) == 1 and pins[0].released_at is not None


def test_a_divergent_replay_lists_the_differences(db, world, user, storage):
    # The original output's bytes were rewritten since (what a destructive
    # erasure does): the recorded hash no longer matches, and the replay's
    # output differs from what is stored -- which must be reported, not hidden.
    original_version = db.scalar(select(DatasetVersion).where(
        DatasetVersion.pipeline_run_id == world["original"].run.id))
    redacted = b"customer,born,amount,as_of,age\nann,1990-06-15,10,2031-03-10,40\n"
    storage.save_upload(relative_path=original_version.file_path, file_bytes=redacted)
    original_version.content_hash = content_digest(redacted)
    db.commit()

    result = _replay(db, world, user, storage)
    assert result.status == "divergent"
    assert result.comparison.rows_equal is False
    assert result.comparison.rows_original == 1 and result.comparison.rows_replay == 2
    assert any("rows differ" in d for d in result.comparison.differences)
    assert result.reason and "rows differ" in result.reason


def test_a_semantic_change_is_an_explicit_incompatibility(db, world, user, storage):
    run = db.get(PipelineRun, world["original"].run.id)
    summary = dict(run.summary_json)
    context = dict(summary["execution_context"])
    context["semantic_version"] = "pipewright-transformations/1999.01"
    summary["execution_context"] = context
    run.summary_json = summary
    db.commit()

    result = _replay(db, world, user, storage)
    assert result.status == "incompatible"
    assert "semantics have changed" in result.reason
    assert result.replay_run_id is None
    # Nothing ran, nothing was published.
    assert db.scalar(select(PipelineRun).where(PipelineRun.run_type == "dataset_transformation_replay")) is None


def test_a_run_from_before_execution_contexts_cannot_be_replayed(db, world, user, storage):
    run = db.get(PipelineRun, world["original"].run.id)
    summary = dict(run.summary_json)
    summary.pop("execution_context")
    run.summary_json = summary
    db.commit()
    result = _replay(db, world, user, storage)
    assert result.status == "unavailable"
    assert "before execution contexts" in result.reason


def test_a_pruned_input_makes_the_replay_unavailable(db, world, user, storage):
    # Supersede the input version so it can be pruned (the head never is)...
    base = db.get(Dataset, world["dataset"].id)
    finalize_dataset_materialization_success(
        db, dataset=base, file_path=base.file_path, file_name="same.csv",
        schema_json=base.schema_json, schema_snapshot=base.schema_snapshot,
        preview_json=base.preview_json, profile_json=base.profile_json,
        row_count=base.row_count, column_count=base.column_count,
        content_hash=content_digest(CSV), created_by_user_id=user.id,
    )
    far = datetime.now(UTC) + timedelta(days=3650)
    schedule_prunes(db, project_id=world["project"].id, cutoff=far, now=far)
    db.commit()
    prune_due(db, project_id=world["project"].id, now=far + timedelta(hours=1), storage=None)

    result = _replay(db, world, user, storage)
    assert result.status == "unavailable"
    assert "pruned by retention" in result.reason
    assert result.replay_run_id is None
    assert db.scalars(select(DatasetVersionPin)).all() == []


def test_an_input_whose_bytes_were_rewritten_is_a_different_input(db, world, user, storage):
    version = db.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == world["dataset"].id))
    version.content_hash = content_digest(b"something else")
    db.commit()
    result = _replay(db, world, user, storage)
    assert result.status == "unavailable"
    assert "no longer holds the bytes" in result.reason


def test_only_a_succeeded_transformation_run_can_be_replayed(db, world, user, storage):
    with pytest.raises(BadRequestError, match="Only transformation runs"):
        replay_pipeline_run(
            db, project_id=world["project"].id, run_id=world["upload_run_id"],
            current_user=user, storage_backend=storage, settings=settings,
        )


def test_the_audit_summary_carries_output_pins_and_replayability(db, world, user, storage):
    audit = get_run_audit_summary(db, world["project"].id, world["original"].run.id, user)
    [out] = audit.output_versions
    assert out.dataset_id == world["original"].dataset.id
    assert out.version_number == 1
    assert out.content_hash == audit.execution_context["outputs"][0]["content_hash"]
    assert audit.replayable is True and audit.replay_reason is None
    assert audit.execution_context["evaluated_at"].startswith("2031-03-10T08:00:00")

    # An upload run has an output pin too (every producer links its version),
    # but is not replayable, and says why.
    upload = get_run_audit_summary(db, world["project"].id, world["upload_run_id"], user)
    assert [v.version_number for v in upload.output_versions] == [1]
    assert upload.output_versions[0].dataset_id == world["dataset"].id
    assert upload.replayable is False
    assert "Only transformation runs" in upload.replay_reason
