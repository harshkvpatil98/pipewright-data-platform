"""Scheduled reports firing without anybody asking."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.models import Project
from service_reporting.models import ReportDelivery, ScheduledReport
from service_reporting.schemas import ReportCreate
from service_reporting.service import create_report, due_reports, run_due_reports
from shared_python.db import Base

OWNER_ID = uuid.UUID("0a0a0a0a-0a0a-0a0a-0a0a-0a0a0a0a0a0a")
SALES = pd.DataFrame({"region": ["north", "south"], "amount": [100, 250]})


class _Storage:
    def read_bytes(self, _path: str) -> bytes:
        return SALES.to_csv(index=False).encode()


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
def world(db: Session) -> dict:
    owner = User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()
    dataset = Dataset(
        project_id=project.id,
        name="sales",
        status="ready",
        ingestion_status="succeeded",
        file_path="datasets/sales.csv",
        file_type="csv",
    )
    db.add(dataset)
    db.commit()

    now = datetime.now(UTC)
    actor = UserRead(
        id=OWNER_ID, username="owner", role="admin", is_active=True,
        created_at=now, updated_at=now,
    )
    return {"owner": owner, "project": project, "dataset": dataset, "actor": actor}


def _report(db: Session, world: dict, **overrides) -> ScheduledReport:
    read = create_report(
        db,
        world["project"].id,
        ReportCreate(
            name="Weekly sales",
            source_kind="dataset",
            source_id=world["dataset"].id,
            file_format="csv",
            **overrides,
        ),
        world["actor"],
    )
    return db.get(ScheduledReport, read.id)


def test_a_report_is_due_once_its_moment_has_passed(db: Session, world: dict):
    report = _report(db, world, cron_expression="0 6 * * *", timezone="UTC")
    assert due_reports(db) == []

    report.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert [item.id for item in due_reports(db)] == [report.id]


def test_a_disabled_report_never_comes_due(db: Session, world: dict):
    report = _report(db, world, cron_expression="0 6 * * *", timezone="UTC", enabled=False)
    report.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert due_reports(db) == []


def test_the_sweep_generates_a_due_report_without_being_asked(db: Session, world: dict):
    report = _report(db, world, cron_expression="0 6 * * *", timezone="UTC")
    report.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert run_due_reports(db, _Storage()) == 1
    assert db.query(ReportDelivery).count() == 1

    db.refresh(report)
    assert report.run_count == 1
    assert report.last_status == "succeeded"


def test_the_schedule_moves_forward_so_it_does_not_run_twice(db: Session, world: dict):
    report = _report(db, world, cron_expression="0 6 * * *", timezone="UTC")
    report.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    run_due_reports(db, _Storage())
    assert run_due_reports(db, _Storage()) == 0


def test_one_failing_report_does_not_stop_the_others(db: Session, world: dict):
    class _Broken:
        def read_bytes(self, _path):
            raise FileNotFoundError("gone")

    good = _report(db, world, cron_expression="0 6 * * *", timezone="UTC")
    good.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    # The storage fails for everything, so the sweep must survive it entirely.
    assert run_due_reports(db, _Broken()) == 0
    db.refresh(good)
    assert good.last_status == "failed"


def test_a_report_whose_author_is_gone_is_disabled_rather_than_failing_forever(
    db: Session, world: dict
):
    report = _report(db, world, cron_expression="0 6 * * *", timezone="UTC")
    report.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    report.created_by_user_id = uuid.uuid4()
    db.commit()

    assert run_due_reports(db, _Storage()) == 0
    db.refresh(report)
    assert report.enabled is False
    assert "no longer has an account" in (report.last_error or "")
