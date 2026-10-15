"""The Studio's expected rows at each step, against what each step did (D2, O2).

Two datasets go through the real ingest, so their statistics come from the
profile every version gets; a recipe that filters, joins, groups and
limits is previewed; and each step's estimate is compared with the rows the
same preview counted. A join reads both datasets' statistics, and dates read
as text are measured as dates, so neither is a guess.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.preview import preview_dataset_transformations
from service_transformations.schemas import TransformationPreviewRequest
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

RNG = np.random.default_rng(7)
ORDERS = 6_000
CUSTOMERS = 800


def _csv(header: str, rows) -> bytes:
    return (header + "\n" + "\n".join(",".join(str(v) for v in row) for row in rows) + "\n").encode()


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
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    regions = RNG.choice(["eu", "us", "apac"], ORDERS, p=[0.5, 0.35, 0.15])
    days = RNG.integers(0, 280, ORDERS)
    orders = _csv("order_id,customer_id,region,amount,placed_on", (
        (i, int(RNG.integers(0, CUSTOMERS)), regions[i], round(float(RNG.gamma(2.0, 40.0)), 2),
         (date(2026, 1, 1) + timedelta(days=int(days[i]))).isoformat()) for i in range(ORDERS)))
    customers = _csv("customer_id,tier", ((i, int(RNG.integers(1, 4))) for i in range(CUSTOMERS)))

    def ingest(name: str, body: bytes):
        return ingest_project_file(
            db, project_id=project.id, dataset_name=name,
            upload_file=IngestionUpload(file_name=f"{name}.csv", content_type="text/csv", file_bytes=body),
            storage_backend=storage, settings=settings, current_user=user,
        ).dataset

    return {"project": project, "orders": ingest("Orders", orders), "customers": ingest("Customers", customers),
            "user": user, "storage": storage}


def _preview(db: Session, world: dict, steps: list[dict]):
    return preview_dataset_transformations(
        db, project_id=world["project"].id, dataset_id=world["orders"].id,
        payload=TransformationPreviewRequest(steps=steps), current_user=world["user"], storage_backend=world["storage"],
    )


def test_each_step_s_expected_rows_are_near_what_it_did(db: Session, world: dict) -> None:
    steps = [
        {"step_type": "filter_rows", "config": {"conditions": [{"column": "region", "operator": "equals", "value": "eu"}]}},
        {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 50}]}},
        # Dates arrive as text from a CSV; parsed, a range over them is still estimated, not guessed.
        {"step_type": "parse_dates", "config": {"columns": ["placed_on"]}},
        {"step_type": "filter_rows", "config": {"conditions": [
            {"column": "placed_on", "operator": "greater_or_equal", "value": "2026-06-01"}]}},
        {"step_type": "join_datasets", "config": {"right_dataset_id": str(world["customers"].id),
                                                  "left_on": ["customer_id"], "right_on": ["customer_id"]}},
        {"step_type": "aggregate", "config": {"group_by": ["tier"],
                                              "aggregations": [{"column": "amount", "function": "sum"}]}},
    ]
    result = _preview(db, world, steps)
    estimates = result.execution_plan.estimates
    assert [estimate.index for estimate in estimates] == [0, 1, 2, 3, 4, 5]
    actual = [outcome.rows_after for outcome in result.step_outcomes]
    for estimate, rows in zip(estimates, actual, strict=True):
        assert not estimate.guessed, estimate
        assert estimate.how
        assert estimate.rows == pytest.approx(rows, rel=0.12), (estimate, rows)
    assert "histogram" in estimates[3].how
    assert "distinct keys" in estimates[4].how
    assert estimates[5].rows == 3  # one row per tier


def test_a_step_the_estimator_cannot_read_says_it_is_a_guess(db: Session, world: dict) -> None:
    steps = [
        {"step_type": "filter_rows", "config": {"conditions": [{"column": "region", "operator": "contains", "value": "e"}]}},
        {"step_type": "limit_rows", "config": {"count": 10}},
    ]
    estimates = _preview(db, world, steps).execution_plan.estimates
    assert estimates[0].guessed and "a guess" in estimates[0].how
    # A limit caps it, but what came before was a guess, so the whole is too.
    assert estimates[1].rows == 10 and estimates[1].guessed


def test_each_version_keeps_the_statistics_it_was_written_with(db: Session, world: dict) -> None:
    from sqlalchemy import select

    from service_datasets.models import Dataset, DatasetVersion
    from service_datasets.service import version_statistics

    dataset = db.get(Dataset, world["orders"].id)
    first = db.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id))
    assert first.statistics_json["rows"] == ORDERS
    stats = version_statistics(db, dataset, first)
    assert stats.rows == ORDERS and stats.columns["region"].distinct == 3
    assert stats.columns["placed_on"].kind == "datetime" and stats.columns["amount"].bounds

    # A version written before statistics were kept: the latest one falls back to the
    # dataset's own profile; an older one has none rather than another version's.
    first.statistics_json = None
    db.commit()
    assert version_statistics(db, dataset, first).rows == ORDERS
    db.add(DatasetVersion(dataset_id=dataset.id, version_number=2, file_path=first.file_path, row_count=1))
    db.commit()
    assert version_statistics(db, dataset, first) is None
    assert version_statistics(db, dataset).rows == ORDERS
