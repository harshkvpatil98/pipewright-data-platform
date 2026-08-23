"""The unattended freshness sweep, and the notification an incident sends."""

from __future__ import annotations

import pytest

from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared_python.db import Base

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

# Registers every model so SQLAlchemy can resolve relationships by name; without
# it, constructing a Dataset here fails on TransformationPipeline.
import api_gateway.metadata  # noqa: F401
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_notifications.models import UserNotification
from service_projects.models import Project

from service_observability import incidents as ops
from service_observability.models import FreshnessPolicy, Incident
from service_observability.schemas import FreshnessPolicyCreate
from service_observability.service import (
    _policy_is_due,
    check_freshness,
    create_freshness_policy,
    sweep_freshness,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _stale(db: Session, dataset: Dataset, hours: int = 9) -> None:
    dataset.last_profiled_at = NOW - timedelta(hours=hours)
    db.commit()


def test_a_never_checked_policy_is_due():
    policy = FreshnessPolicy(max_age_minutes=60, last_checked_at=None)
    assert _policy_is_due(policy, NOW) is True


def test_a_policy_checked_a_moment_ago_is_not_due_again():
    """A worker ticking every 30 seconds must not re-check a six-hour promise."""
    policy = FreshnessPolicy(max_age_minutes=360, last_checked_at=NOW - timedelta(seconds=30))
    assert _policy_is_due(policy, NOW) is False


def test_the_check_interval_scales_with_the_promise():
    tight = FreshnessPolicy(max_age_minutes=4, last_checked_at=NOW - timedelta(minutes=1.5))
    loose = FreshnessPolicy(max_age_minutes=1440, last_checked_at=NOW - timedelta(minutes=30))
    assert _policy_is_due(tight, NOW) is True
    # A daily promise is checked hourly, not every six hours.
    assert _policy_is_due(loose, NOW) is False
    assert _policy_is_due(
        FreshnessPolicy(max_age_minutes=1440, last_checked_at=NOW - timedelta(minutes=61)), NOW
    )


def test_the_sweep_covers_every_project_without_being_asked(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    other = Project(name="Other", slug="other", owner_user_id=user.id, status="active")
    db.add(other)
    db.flush()
    other_dataset = Dataset(
        project_id=other.id, name="feeds", status="ready", ingestion_status="succeeded"
    )
    db.add(other_dataset)
    db.commit()

    create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=60), user
    )
    create_freshness_policy(
        db,
        other.id,
        FreshnessPolicyCreate(dataset_id=other_dataset.id, max_age_minutes=60),
        UserRead(**{**user.model_dump(), "id": user.id}),
    )
    _stale(db, dataset)
    _stale(db, other_dataset)

    assert sweep_freshness(db, now=NOW) == 2
    assert db.query(Incident).count() == 2


def test_repeated_sweeps_do_not_inflate_the_occurrence_count(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=360), user
    )
    _stale(db, dataset)

    sweep_freshness(db, now=NOW)
    for seconds in (30, 60, 90, 120):
        sweep_freshness(db, now=NOW + timedelta(seconds=seconds))

    assert db.query(Incident).one().occurrence_count == 1


def test_a_sweep_after_the_interval_records_the_recurrence(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=60), user
    )
    _stale(db, dataset)

    sweep_freshness(db, now=NOW)
    sweep_freshness(db, now=NOW + timedelta(minutes=20))

    assert db.query(Incident).one().occurrence_count == 2


def test_opening_an_incident_notifies_the_project_owner(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=60), user
    )
    _stale(db, dataset)
    check_freshness(db, project.id, user, now=NOW)

    notification = db.query(UserNotification).one()
    assert notification.user_id == project.owner_user_id
    assert notification.type == "incident"
    assert notification.level == "error"
    assert "stale" in notification.title


def test_a_recurrence_does_not_send_another_notification(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    """The second night of the same failure must not send a second message."""
    create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=60), user
    )
    _stale(db, dataset)

    check_freshness(db, project.id, user, now=NOW)
    check_freshness(db, project.id, user, now=NOW + timedelta(hours=1))

    assert db.query(UserNotification).count() == 1


def test_a_notification_failure_never_loses_the_incident(
    db: Session, project: Project, monkeypatch
):
    """The incident is the record; the message is a courtesy."""
    import service_notifications.service as notifications

    def explode(*_args, **_kwargs):
        raise RuntimeError("mail server down")

    monkeypatch.setattr(notifications, "create_user_notification", explode)

    incident = ops.report(
        db,
        project_id=project.id,
        fingerprint=ops.fingerprint_for("quality", "rule-x"),
        title="Rule failed",
        summary="It failed.",
        source_kind="quality",
    )
    db.commit()
    assert db.get(Incident, incident.id) is not None


def test_a_missing_project_owner_is_not_an_error(db: Session):
    orphan = Project(name="Orphan", slug="orphan", owner_user_id=None, status="active")
    db.add(orphan)
    db.commit()

    ops.report(
        db,
        project_id=orphan.id,
        fingerprint=ops.fingerprint_for("drift", uuid.uuid4()),
        title="Drift",
        summary=None,
        source_kind="drift",
    )
    db.commit()
    assert db.query(Incident).count() == 1
    assert db.query(UserNotification).count() == 0


# Fixtures are defined per module rather than in a shared conftest: this suite
# runs with `--import-mode=importlib` and no `__init__.py`, so two conftest.py
# files in different service directories collide on module name and one
# silently supplies the other's fixtures.

OWNER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


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
