"""A run records how it ran: frozen instant, steps, input and output pins (§3).

Driven against a real (SQLite) database with the same service functions the
API calls: a file is ingested, a pipeline with a clock-dependent formula is
run, and the run's summary must carry a context from which the result can be
reproduced -- and the pins must point at the versions that actually exist.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import DatasetVersion
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.execution_context import (
    SEMANTIC_VERSION,
    context_from_run,
    steps_digest,
)
from service_transformations.ir.clock import frozen_clock
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import TransformationPipelineCreate
from service_transformations.service import create_transformation_pipeline
from shared_python.db import Base
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
    project = create_project(db, ProjectCreate(name="Ctx", description=None), user)
    uploaded = ingest_project_file(
        db, project_id=project.id, dataset_name="people",
        upload_file=IngestionUpload(file_name="people.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    pipeline = create_transformation_pipeline(
        db, project_id=project.id, dataset_id=uploaded.dataset.id,
        payload=TransformationPipelineCreate(name="ages", steps_json=STEPS), current_user=user,
    )
    return {"project": project, "dataset": uploaded.dataset, "pipeline": pipeline}


def _run(db, world, user, storage):
    return run_saved_transformation_pipeline(
        db, project_id=world["project"].id, pipeline_id=world["pipeline"].id,
        current_user=user, storage_backend=storage, settings=settings, notify_on_complete=False,
    )


def test_a_run_records_a_complete_execution_context(db, world, user, storage):
    result = _run(db, world, user, storage)
    context = context_from_run(result.run.summary_json)
    assert context is not None

    assert context.semantic_version == SEMANTIC_VERSION
    assert context.timezone == "UTC"
    assert context.evaluated_at.tzinfo is not None
    # The instant was frozen at run start: now, give or take the run itself.
    assert abs((datetime.now(UTC) - context.evaluated_at).total_seconds()) < 30
    # The steps that ran -- a snapshot, with a digest a reader can compare.
    assert context.steps == STEPS
    assert context.steps_digest == steps_digest(STEPS)

    # The input pin is the base dataset's head version, hash and all.
    base_version = db.scalar(select(DatasetVersion).where(
        DatasetVersion.dataset_id == world["dataset"].id))
    [pin] = context.inputs
    assert pin.role == "base"
    assert pin.dataset_id == str(world["dataset"].id)
    assert pin.version_number == base_version.version_number == 1
    assert pin.content_hash == base_version.content_hash

    # The output pin is the version this run published -- linked to the run.
    [out] = context.outputs
    published = db.scalar(select(DatasetVersion).where(
        DatasetVersion.pipeline_run_id == result.run.id))
    assert out.role == "output"
    assert out.dataset_id == str(result.dataset.id) == str(published.dataset_id)
    assert out.version_number == published.version_number == 1
    assert out.content_hash == published.content_hash
    assert context.replay_of is None


def test_clock_functions_evaluate_at_the_recorded_instant(db, world, user, storage):
    # A run freezes whatever the evaluation instant is when it starts -- the
    # real clock normally, an outer frozen one here (a replay installs the
    # recorded instant the same way). The data must agree with the context:
    # the recorded `as_of` IS the recorded evaluated_at.
    instant = datetime(2031, 3, 10, 8, 0, tzinfo=UTC)
    with frozen_clock(instant):
        result = _run(db, world, user, storage)
    context = context_from_run(result.run.summary_json)
    assert context.evaluated_at == instant

    rows = {row["customer"]: row for row in result.dataset.preview_json["rows"]}
    assert str(rows["ann"]["as_of"]).startswith("2031-03-10")
    assert int(rows["ann"]["age"]) == 40
    assert int(rows["bo"]["age"]) == 31
    assert "cy" not in rows  # filtered: null amount is not > 0 (three-valued)


def test_a_failed_run_still_records_its_context(db, world, user, storage):
    from service_transformations.models import TransformationPipeline

    pipeline = db.get(TransformationPipeline, world["pipeline"].id)
    pipeline.steps_json = [
        {"step_type": "filter_rows",
         "config": {"conditions": [{"column": "nope", "operator": "greater_than", "value": 0}]}}
    ]
    db.commit()
    from shared_python.errors import ApplicationError

    with pytest.raises(ApplicationError):
        _run(db, world, user, storage)
    from service_pipeline_runs.models import PipelineRun

    run = db.scalar(select(PipelineRun).where(PipelineRun.status == "failed"))
    context = context_from_run(run.summary_json)
    assert context is not None
    assert [pin.role for pin in context.inputs] == ["base"]
    assert context.outputs == []
