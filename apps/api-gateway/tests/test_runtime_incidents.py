"""Stalled-queue incidents: open when work is stuck, resolve when it moves.

This is the escalation the runtime panel earns -- a durable, notifying record
that a queue nobody is draining. These pin the three cases that matter: it
fires only past the threshold with no worker, it does *not* fire while a worker
is beating, and it closes itself the moment work moves again.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.runtime_incidents import FINGERPRINT, sweep_runtime_incidents
from service_observability import incidents
from service_observability.models import Incident
from service_observability.runtime import record_heartbeat
from service_projects.models import Project
from service_workflows.models import Workflow, WorkflowRun
from shared_python.db import Base

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


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


def _project(db: Session, name: str = "Ops") -> Project:
    project = Project(name=name, slug=name.lower(), status="active")
    db.add(project)
    db.flush()
    return project


def _queued_run(db: Session, project: Project, *, queued_at: datetime, status: str = "queued") -> WorkflowRun:
    workflow = Workflow(project_id=project.id, name="wf")
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        workflow_id=workflow.id, project_id=project.id, status=status, queued_at=queued_at
    )
    db.add(run)
    db.flush()
    return run


def _active(db: Session) -> list[Incident]:
    return incidents.active_by_fingerprint(db, FINGERPRINT)


def test_a_run_queued_past_the_threshold_with_no_worker_opens_an_incident(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    db.commit()

    result = sweep_runtime_incidents(db, now=NOW)
    assert result["opened"] == 1
    active = _active(db)
    assert len(active) == 1
    assert active[0].project_id == project.id
    assert active[0].source_kind == "runtime"


def test_a_fresh_worker_heartbeat_means_no_incident(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    # The worker is beating -- it is draining, just slowly. Not an incident.
    record_heartbeat(db, component="workflow-worker", host="h1", interval_seconds=5, now=NOW)
    db.commit()

    result = sweep_runtime_incidents(db, now=NOW)
    assert result["opened"] == 0
    assert _active(db) == []


def test_a_recently_queued_run_is_not_yet_an_incident(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=5))
    db.commit()

    result = sweep_runtime_incidents(db, now=NOW)
    assert result["opened"] == 0
    assert _active(db) == []


def test_a_running_workflow_means_the_queue_is_being_drained(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=10), status="running")
    db.commit()

    result = sweep_runtime_incidents(db, now=NOW)
    assert result["opened"] == 0


def test_the_incident_resolves_itself_once_the_queue_drains(db: Session) -> None:
    project = _project(db)
    run = _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    db.commit()

    sweep_runtime_incidents(db, now=NOW)
    assert len(_active(db)) == 1

    # The worker came back and finished the run: the queue is empty now.
    run.status = "succeeded"
    db.commit()

    result = sweep_runtime_incidents(db, now=NOW + timedelta(minutes=1))
    assert result["resolved"] == 1
    assert _active(db) == []


def test_the_incident_resolves_when_a_worker_comes_back(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    db.commit()

    sweep_runtime_incidents(db, now=NOW)
    assert len(_active(db)) == 1

    # Work is still queued, but a worker is beating again -- it will drain it.
    record_heartbeat(db, component="workflow-worker", host="h1", interval_seconds=5, now=NOW)
    db.commit()
    result = sweep_runtime_incidents(db, now=NOW + timedelta(seconds=30))
    assert result["resolved"] == 1
    assert _active(db) == []


def test_the_sweep_is_idempotent_across_passes(db: Session) -> None:
    project = _project(db)
    _queued_run(db, project, queued_at=NOW - timedelta(minutes=45))
    db.commit()

    sweep_runtime_incidents(db, now=NOW)
    sweep_runtime_incidents(db, now=NOW + timedelta(minutes=1))
    # Still exactly one incident -- recurrence bumps the existing one, not a new row.
    assert len(_active(db)) == 1
