"""A recipe writes every run into one dataset (adoption-readiness A4, U1).

A replay is the deliberate exception: it publishes beside the original so the
two can be compared, and must not become the recipe's output.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.models import TransformationPipeline
from service_transformations.replay import replay_pipeline_run
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import TransformationPipelineCreate
from service_transformations.service import create_transformation_pipeline
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

CSV = b"customer,amount\nann,10\nbo,20\ncy,\n"
STEPS = [{"step_type": "drop_null_rows", "config": {"how": "any"}}]


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
    row = User(username="runner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username=row.username, role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    uploaded = ingest_project_file(
        db, project_id=project.id, dataset_name="orders",
        upload_file=IngestionUpload(file_name="orders.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    )
    pipeline = create_transformation_pipeline(
        db, project_id=project.id, dataset_id=uploaded.dataset.id,
        payload=TransformationPipelineCreate(name="Tidy orders", steps_json=STEPS), current_user=user,
    )
    return {"project": project, "pipeline": pipeline, "user": user, "storage": storage}


def _run(db: Session, world: dict):
    return run_saved_transformation_pipeline(
        db, project_id=world["project"].id, pipeline_id=world["pipeline"].id, current_user=world["user"],
        storage_backend=world["storage"], settings=settings, notify_on_complete=False,
    )


def _versions(db: Session, dataset_id) -> int:
    return int(db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)))


def test_runs_of_a_recipe_add_versions_to_one_dataset(db: Session, world: dict) -> None:
    first = _run(db, world)
    second = _run(db, world)
    assert second.dataset.id == first.dataset.id
    assert first.dataset.name == "Tidy orders (result)"
    assert _versions(db, first.dataset.id) == 2
    assert db.get(TransformationPipeline, world["pipeline"].id).output_dataset_id == first.dataset.id


def test_a_replay_publishes_beside_the_output_and_does_not_replace_it(db: Session, world: dict) -> None:
    first = _run(db, world)
    replayed = replay_pipeline_run(
        db, project_id=world["project"].id, run_id=first.run.id, current_user=world["user"],
        storage_backend=world["storage"], settings=settings,
    )
    assert replayed.replay_dataset_id is not None
    assert replayed.replay_dataset_id != first.dataset.id
    assert db.get(TransformationPipeline, world["pipeline"].id).output_dataset_id == first.dataset.id
    assert _run(db, world).dataset.id == first.dataset.id


def test_a_deleted_output_is_started_again(db: Session, world: dict) -> None:
    first = _run(db, world)
    db.delete(db.get(Dataset, first.dataset.id))
    db.commit()
    second = _run(db, world)
    assert second.dataset.id != first.dataset.id
    assert db.get(TransformationPipeline, world["pipeline"].id).output_dataset_id == second.dataset.id
