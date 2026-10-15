"""The one-click sample workspace, built end to end against a real database.

The demo's whole value is that it is composed from the same service functions a
user's own clicks call -- so the honest way to prove it is to run it and check
that a project, a dataset, a pipeline, a rule, and a schedule all actually land
in the database. This is the guided first win a new evaluator sees; if any one
of the four pieces silently failed, the checklist would never reach 4 of 4.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from api_gateway.demo import create_demo_project
from service_auth.models import User
from service_auth.schemas import UserRead
from service_quality.models import DataQualityRule
from service_schedules.models import ScheduledOperation
from service_reporting.models import Dashboard, SavedChart
from service_transformations.models import TransformationPipeline
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend


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
def current_user(db: Session) -> UserRead:
    row = User(username="platform-admin", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    return UserRead(
        id=row.id, username=row.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


def _count(db: Session, model, project_id: uuid.UUID) -> int:
    return len(list(db.scalars(select(model).where(model.project_id == project_id))))


def test_demo_seeds_a_complete_worked_example(
    db: Session, current_user: UserRead, storage: LocalStorageBackend
) -> None:
    detail = create_demo_project(
        db, current_user=current_user, storage_backend=storage, settings=settings
    )

    # The project exists with the file it read and the recipe's cleaned result.
    assert detail.name == "Acme Retail (demo)"
    assert detail.dataset_count == 2

    # Every one of the four checklist steps produced its artifact -- so a fresh
    # evaluator opening this project sees 4 of 4 done, not a half-built demo.
    assert _count(db, TransformationPipeline, detail.id) == 1
    assert _count(db, DataQualityRule, detail.id) == 1
    assert _count(db, ScheduledOperation, detail.id) == 1

    # The story runs all the way to something a stakeholder opens: a chart on a
    # dashboard, not a pipeline that stops at the data layer.
    assert _count(db, SavedChart, detail.id) == 1
    assert _count(db, Dashboard, detail.id) == 1


def test_demo_schedule_targets_the_pipeline_it_created(
    db: Session, current_user: UserRead, storage: LocalStorageBackend
) -> None:
    detail = create_demo_project(
        db, current_user=current_user, storage_backend=storage, settings=settings
    )
    pipeline = db.scalars(
        select(TransformationPipeline).where(TransformationPipeline.project_id == detail.id)
    ).one()
    schedule = db.scalars(
        select(ScheduledOperation).where(ScheduledOperation.project_id == detail.id)
    ).one()

    # The schedule must point at the pipeline the seed just built, or "Daily
    # orders refresh" would run against nothing.
    assert schedule.target_config_json.get("pipeline_id") == str(pipeline.id)


def test_the_demo_does_what_it_says(
    db: Session, current_user: UserRead, storage: LocalStorageBackend
) -> None:
    """A9, Z1: the dashboard said "shaped and validated" while the recipe and
    the check had never run and the chart read the raw file."""
    from service_datasets.models import Dataset
    from service_observability.models import MetricAlert
    from service_quality.models import DataQualityRunResult

    detail = create_demo_project(db, current_user=current_user, storage_backend=storage, settings=settings)
    datasets = {row.name: row for row in db.scalars(select(Dataset).where(Dataset.project_id == detail.id))}
    raw = datasets["Customer orders (sample)"]
    [cleaned] = [row for name, row in datasets.items() if name != raw.name]
    assert (raw.row_count, cleaned.row_count) == (12, 10), "the recipe ran: no missing or negative amounts"

    [evaluation] = db.scalars(select(DataQualityRunResult).where(DataQualityRunResult.dataset_id == raw.id)).all()
    assert evaluation.status == "failed", "the check ran, and caught the order with no email"

    [chart] = db.scalars(select(SavedChart).where(SavedChart.project_id == detail.id)).all()
    assert chart.dataset_id == cleaned.id, "the chart reads the cleaned orders"
    [alert] = db.scalars(select(MetricAlert).where(MetricAlert.project_id == detail.id)).all()
    assert (alert.dataset_id, alert.metric_key) == (cleaned.id, "row_count")

    dashboard = db.scalars(select(Dashboard).where(Dashboard.project_id == detail.id)).one()
    words = " ".join([detail.description or "", dashboard.description or "", chart.description or "", *datasets])
    for retired in ("—", "pipeline", "publish", "rule", "shaped", "validated"):
        assert retired not in words.lower(), f"the demo says “{retired}”"
