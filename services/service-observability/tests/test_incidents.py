"""Incident grouping: one problem, however many times it happens."""

from __future__ import annotations

from service_auth.schemas import UserRead

from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from service_datasets.models import Dataset
from shared_python.db import Base

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from service_observability import incidents as ops
from service_observability.models import Incident
from service_projects.models import Project
from shared_python.errors import BadRequestError, NotFoundError

NOW = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)


def _report(db: Session, project: Project, *, severity="high", now=NOW, summary="It failed."):
    return ops.report(
        db,
        project_id=project.id,
        fingerprint=ops.fingerprint_for("quality", "rule-1"),
        title="Email must not be null",
        summary=summary,
        source_kind="quality",
        source_id="rule-1",
        severity=severity,
        now=now,
    )


def test_a_fingerprint_excludes_anything_time_varying():
    assert ops.fingerprint_for("quality", "rule-1") == "quality:rule-1"
    assert ops.fingerprint_for("anomaly", "ds", "row_count", None) == "anomaly:ds:row_count:-"


def test_an_unknown_source_kind_is_rejected():
    with pytest.raises(BadRequestError):
        ops.fingerprint_for("vibes", "x")


def test_the_first_report_opens_an_incident_with_a_timeline(db: Session, project: Project):
    incident = _report(db, project)
    db.commit()

    assert incident.status == "open"
    assert incident.occurrence_count == 1
    events = ops.timeline(db, incident.id)
    assert [event.kind for event in events] == ["opened"]


def test_repeats_land_on_the_same_incident(db: Session, project: Project):
    first = _report(db, project)
    for index in range(1, 5):
        _report(db, project, now=NOW + timedelta(days=index))
    db.commit()

    assert db.query(Incident).count() == 1
    db.refresh(first)
    assert first.occurrence_count == 5
    assert first.last_seen_at.replace(tzinfo=UTC) == NOW + timedelta(days=4)


def test_consecutive_recurrences_collapse_into_one_timeline_entry(db: Session, project: Project):
    """Thirty nightly failures should not produce thirty lines to scroll past."""
    incident = _report(db, project)
    for index in range(1, 30):
        _report(db, project, now=NOW + timedelta(days=index))
    db.commit()

    events = ops.timeline(db, incident.id)
    assert [event.kind for event in events] == ["opened", "recurred"]
    assert "Seen 30 times" in events[-1].message


def test_a_comment_between_recurrences_starts_a_new_recurrence_entry(db: Session, project: Project):
    incident = _report(db, project)
    _report(db, project, now=NOW + timedelta(days=1))
    ops.comment(db, incident, message="Looking into it", actor_user_id=None)
    _report(db, project, now=NOW + timedelta(days=2))
    db.commit()

    assert [event.kind for event in ops.timeline(db, incident.id)] == [
        "opened",
        "recurred",
        "comment",
        "recurred",
    ]


def test_severity_escalates_but_never_quietly_drops(db: Session, project: Project):
    incident = _report(db, project, severity="medium")
    _report(db, project, severity="critical")
    _report(db, project, severity="low")
    db.commit()

    db.refresh(incident)
    assert incident.severity == "critical"


def test_a_resolved_incident_does_not_absorb_a_new_occurrence(db: Session, project: Project):
    first = _report(db, project)
    ops.resolve(db, first, note="fixed", actor_user_id=None)
    db.commit()

    second = _report(db, project, now=NOW + timedelta(days=1))
    db.commit()

    assert second.id != first.id
    assert db.query(Incident).count() == 2


def test_auto_resolve_closes_the_open_incident_and_says_why(db: Session, project: Project):
    incident = _report(db, project)
    db.commit()

    closed = ops.auto_resolve(
        db, project_id=project.id, fingerprint=incident.fingerprint, message="Passing again."
    )
    db.commit()

    assert closed is not None
    assert closed.status == "resolved"
    assert [event.kind for event in ops.timeline(db, incident.id)][-1] == "auto_resolved"


def test_auto_resolve_is_a_no_op_when_nothing_is_open(db: Session, project: Project):
    assert (
        ops.auto_resolve(
            db, project_id=project.id, fingerprint="quality:nothing", message="fine"
        )
        is None
    )


def test_acknowledging_keeps_the_incident_active(db: Session, project: Project):
    incident = _report(db, project)
    ops.acknowledge(db, incident, actor_user_id=None)
    db.commit()

    assert incident.status == "acknowledged"
    # An acknowledged incident still absorbs repeats rather than opening a new one.
    _report(db, project, now=NOW + timedelta(days=1))
    db.commit()
    assert db.query(Incident).count() == 1


def test_resolving_twice_is_rejected(db: Session, project: Project):
    incident = _report(db, project)
    ops.resolve(db, incident, note=None, actor_user_id=None)
    db.commit()
    with pytest.raises(BadRequestError):
        ops.resolve(db, incident, note=None, actor_user_id=None)


def test_reopening_requires_a_resolved_incident(db: Session, project: Project):
    incident = _report(db, project)
    with pytest.raises(BadRequestError):
        ops.reopen(db, incident, reason=None, actor_user_id=None)

    ops.resolve(db, incident, note=None, actor_user_id=None)
    ops.reopen(db, incident, reason="came back", actor_user_id=None)
    db.commit()
    assert incident.status == "open"
    assert incident.resolved_at is None


def test_an_empty_comment_is_rejected(db: Session, project: Project):
    incident = _report(db, project)
    with pytest.raises(BadRequestError):
        ops.comment(db, incident, message="   ", actor_user_id=None)


def test_incidents_from_another_project_are_not_found(db: Session, project: Project):
    incident = _report(db, project)
    db.commit()
    with pytest.raises(NotFoundError):
        ops.get_incident(db, uuid.uuid4(), incident.id)


def test_different_fingerprints_are_different_incidents(db: Session, project: Project):
    _report(db, project)
    ops.report(
        db,
        project_id=project.id,
        fingerprint=ops.fingerprint_for("quality", "rule-2"),
        title="Another rule",
        summary=None,
        source_kind="quality",
        severity="high",
    )
    db.commit()
    assert db.query(Incident).count() == 2
    assert ops.open_count(db, project.id) == 2


# Fixtures are defined per module rather than in a shared conftest: this suite
# runs with `--import-mode=importlib` and no `__init__.py`, so two conftest.py
# files in different service directories collide on module name and one
# silently supplies the other's fixtures.

OWNER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user() -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=OWNER_ID, username="owner", role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def project(db: Session, user: UserRead) -> Project:
    row = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def dataset(db: Session, project: Project) -> Dataset:
    row = Dataset(
        project_id=project.id,
        name="orders",
        status="ready",
        ingestion_status="succeeded",
        profile_json={
            "row_count": 1000,
            "column_count": 3,
            "duplicate_row_percentage": 0.0,
            "completeness_score": 99.0,
            "columns": [{"name": "email", "null_percentage": 1.0, "unique_count": 990}],
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
