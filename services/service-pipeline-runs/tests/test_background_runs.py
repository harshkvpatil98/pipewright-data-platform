"""Long work done by the worker instead of the request (adoption-readiness A7, X3)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_pipeline_runs import background
from service_pipeline_runs.models import PipelineRun
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError


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
def run(db: Session) -> PipelineRun:
    owner = User(username="o", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="P", slug=f"p-{uuid.uuid4().hex[:6]}", status="active", owner_user_id=owner.id)
    db.add(project)
    db.flush()
    row = PipelineRun(project_id=project.id, triggered_by_user_id=owner.id, run_type="test_work", status="queued")
    db.add(row)
    db.commit()
    return background.queue(db, run=row, request={"n": 3}, message="Waiting for the background worker.")


def test_a_queued_run_is_done_by_the_worker_with_progress(db: Session, run: PipelineRun) -> None:
    def work(session, claimed, _storage, _settings):
        assert claimed.status == "running" and claimed.claim_owner_id == "w1"
        for step in range(claimed.request_json["n"]):
            background.progress(session, claimed, "work", f"Step {step + 1} of 3.")
        claimed.status = "succeeded"
        session.commit()

    background.register("test_work", work)
    done = background.run_next(db, storage_backend=None, settings=None, owner="w1")
    assert done.status == "succeeded"
    assert [event["message"] for event in done.logs_json["events"]][-1] == "Step 3 of 3."
    assert done.claim_owner_id is None
    assert background.run_next(db, storage_backend=None, settings=None, owner="w1") is None


def test_a_refusal_fails_the_run_with_its_reason(db: Session, run: PipelineRun) -> None:
    def refuse(*_args):
        raise BadRequestError("The destination is turned off.")

    background.register("test_work", refuse)
    done = background.run_next(db, storage_backend=None, settings=None, owner="w1")
    assert done.status == "failed"
    assert done.logs_json["events"][-1]["message"] == "The destination is turned off."


def test_a_crash_fails_the_run_without_the_traceback(db: Session, run: PipelineRun) -> None:
    def crash(*_args):
        raise RuntimeError("socket closed")

    background.register("test_work", crash)
    done = background.run_next(db, storage_backend=None, settings=None, owner="w1")
    assert done.status == "failed"
    assert "socket closed" not in done.logs_json["events"][-1]["message"]


def test_a_run_whose_worker_stopped_is_failed_not_repeated(db: Session, run: PipelineRun) -> None:
    background.register("test_work", lambda *_args: None)
    claimed = background.claim_next(db, owner="w1")
    assert background.release_stalled(db, now=datetime.now(UTC) + timedelta(seconds=background.LEASE_SECONDS + 1)) == 1
    db.refresh(claimed)
    assert claimed.status == "failed"
    assert "stopped responding" in claimed.logs_json["events"][-1]["message"]
