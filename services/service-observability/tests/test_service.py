"""Metric history, anomaly scans, and freshness checks over real rows."""

from __future__ import annotations

from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared_python.db import Base

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.models import Project
from shared_python.errors import BadRequestError, NotFoundError

from service_observability.models import DatasetMetric, Incident
from service_observability.schemas import (
    FreshnessPolicyCreate,
    FreshnessPolicyUpdate,
    IncidentCommentRequest,
)
from service_observability.service import (
    acknowledge_incident,
    assign_incident,
    capture_dataset_metrics,
    check_freshness,
    comment_on_incident,
    create_freshness_policy,
    delete_freshness_policy,
    get_metric_history,
    list_freshness_policies,
    list_incidents,
    record_dataset_metrics,
    resolve_incident,
    scan_dataset_anomalies,
    update_freshness_policy,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _seed_history(db, project, dataset, key, values, *, column=None, start=NOW):
    for index, value in enumerate(values):
        db.add(
            DatasetMetric(
                project_id=project.id,
                dataset_id=dataset.id,
                metric_key=key,
                column_name=column,
                value=float(value),
                captured_at=start - timedelta(days=len(values) - index),
            )
        )
    db.commit()


# ---- recording and history ----


def test_capture_writes_one_row_per_metric(db: Session, project: Project, dataset: Dataset, user: UserRead):
    response = capture_dataset_metrics(db, project.id, dataset.id, user)
    assert response.metrics_recorded == 6  # 4 dataset-wide + 2 for the email column
    assert db.query(DatasetMetric).count() == 6


def test_capturing_an_unprofiled_dataset_is_rejected(db: Session, project: Project, user: UserRead):
    bare = Dataset(project_id=project.id, name="bare", status="registered", ingestion_status="pending")
    db.add(bare)
    db.commit()
    with pytest.raises(BadRequestError) as caught:
        capture_dataset_metrics(db, project.id, bare.id, user)
    assert "not been profiled" in str(caught.value.detail)


def test_recording_never_raises_on_a_missing_profile(db: Session, project: Project, dataset: Dataset):
    assert record_dataset_metrics(db, project_id=project.id, dataset_id=dataset.id, profile=None) == 0


def test_history_returns_a_series_per_metric_oldest_first(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "row_count", [100, 200, 300])
    response = get_metric_history(db, project.id, dataset.id, user, metric_key="row_count")

    assert len(response.series) == 1
    series = response.series[0]
    assert [point.value for point in series.points] == [100.0, 200.0, 300.0]
    assert series.latest == 300.0
    assert series.previous == 200.0
    assert series.change_percentage == 50.0


def test_history_separates_columns_of_the_same_metric(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "null_percentage", [1, 2], column="email")
    _seed_history(db, project, dataset, "null_percentage", [5, 6], column="phone")
    response = get_metric_history(db, project.id, dataset.id, user, metric_key="null_percentage")
    assert {series.column_name for series in response.series} == {"email", "phone"}


def test_history_labels_read_like_english(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "null_percentage", [1, 2], column="email")
    series = get_metric_history(db, project.id, dataset.id, user).series[0]
    assert series.label == "null rate of 'email'"
    assert series.unit == "%"


def test_history_for_another_users_project_is_not_found(
    db: Session, project: Project, dataset: Dataset
):
    now = datetime.now(UTC)
    stranger = UserRead(
        id=uuid.uuid4(), username="x", role="admin", is_active=True, created_at=now, updated_at=now
    )
    with pytest.raises(NotFoundError):
        get_metric_history(db, project.id, dataset.id, stranger)


# ---- anomalies ----


def test_an_anomaly_scan_finds_the_metric_that_moved(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "row_count", [1000, 1002, 998, 1001, 999, 1000, 120])
    response = scan_dataset_anomalies(db, project.id, dataset.id, user)

    flagged = [item for item in response.anomalies if item.status == "anomalous"]
    assert len(flagged) == 1
    assert flagged[0].metric_key == "row_count"
    assert flagged[0].severity == "critical"
    assert "1 of 1 tracked metrics" in response.summary


def test_a_scan_with_no_history_says_so_rather_than_reporting_all_clear(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    response = scan_dataset_anomalies(db, project.id, dataset.id, user)
    assert response.checked_count == 0
    assert "No metrics have been recorded" in response.summary


def test_a_scan_with_short_history_reports_no_baseline(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "row_count", [1000, 5])
    response = scan_dataset_anomalies(db, project.id, dataset.id, user)
    assert [item.status for item in response.anomalies] == ["no_baseline"]
    assert "No baselines yet" in response.summary


def test_a_scan_can_raise_incidents(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "row_count", [1000, 1002, 998, 1001, 999, 1000, 120])
    scan_dataset_anomalies(db, project.id, dataset.id, user, open_incidents=True)

    incident = db.query(Incident).one()
    assert incident.source_kind == "anomaly"
    assert incident.dataset_id == dataset.id
    assert "row count" in incident.summary


def test_rescanning_the_same_anomaly_does_not_open_a_second_incident(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _seed_history(db, project, dataset, "row_count", [1000, 1002, 998, 1001, 999, 1000, 120])
    scan_dataset_anomalies(db, project.id, dataset.id, user, open_incidents=True)
    scan_dataset_anomalies(db, project.id, dataset.id, user, open_incidents=True)

    assert db.query(Incident).count() == 1
    assert db.query(Incident).one().occurrence_count == 2


# ---- freshness ----


def _policy(db, project, dataset, user, minutes=60):
    return create_freshness_policy(
        db, project.id, FreshnessPolicyCreate(dataset_id=dataset.id, max_age_minutes=minutes), user
    )


def test_a_dataset_can_only_have_one_freshness_policy(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    _policy(db, project, dataset, user)
    with pytest.raises(BadRequestError):
        _policy(db, project, dataset, user)


def test_policies_can_be_updated_and_deleted(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    policy = _policy(db, project, dataset, user)
    updated = update_freshness_policy(
        db, project.id, policy.id, FreshnessPolicyUpdate(max_age_minutes=30, enabled=False), user
    )
    assert updated.max_age_minutes == 30
    assert updated.enabled is False

    delete_freshness_policy(db, project.id, policy.id, user)
    assert list_freshness_policies(db, project.id, user).items == []


def test_a_stale_dataset_opens_an_incident(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)

    response = check_freshness(db, project.id, user, now=NOW)
    assert response.stale == 1
    assert response.incidents_opened == 1
    assert db.query(Incident).one().source_kind == "freshness"


def test_a_dataset_that_becomes_fresh_again_closes_its_incident(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)
    check_freshness(db, project.id, user, now=NOW)

    dataset.last_profiled_at = NOW - timedelta(minutes=5)
    db.commit()
    response = check_freshness(db, project.id, user, now=NOW)

    assert response.incidents_resolved == 1
    assert db.query(Incident).one().status == "resolved"


def test_repeated_staleness_is_one_incident_that_recurs(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)

    check_freshness(db, project.id, user, now=NOW)
    second = check_freshness(db, project.id, user, now=NOW + timedelta(hours=1))

    assert second.incidents_opened == 0
    assert db.query(Incident).count() == 1
    assert db.query(Incident).one().occurrence_count == 2


def test_a_disabled_policy_is_not_checked(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(days=5)
    db.commit()
    policy = _policy(db, project, dataset, user, minutes=60)
    update_freshness_policy(db, project.id, policy.id, FreshnessPolicyUpdate(enabled=False), user)

    assert check_freshness(db, project.id, user, now=NOW).checked == 0


# ---- incident list and actions ----


def test_incident_actions_write_a_readable_timeline(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)
    check_freshness(db, project.id, user, now=NOW)
    incident_id = db.query(Incident).one().id

    acknowledge_incident(db, project.id, incident_id, user)
    comment_on_incident(
        db, project.id, incident_id, IncidentCommentRequest(message="Restarting the job"), user
    )
    detail = resolve_incident(db, project.id, incident_id, "Job restarted", user)

    assert detail.status == "resolved"
    assert [event.kind for event in detail.events] == [
        "opened",
        "acknowledged",
        "comment",
        "resolved",
    ]
    assert [event.sequence for event in detail.events] == [1, 2, 3, 4]


def test_assigning_records_who_owns_it(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    from service_auth.models import User

    db.add(User(id=user.id, username="owner", password_hash="x", role="admin", is_active=True))
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)
    check_freshness(db, project.id, user, now=NOW)
    incident_id = db.query(Incident).one().id

    detail = assign_incident(db, project.id, incident_id, user.id, user)
    assert detail.assignee_name == "owner"
    assert detail.events[-1].message == "Assigned to owner."


def test_the_incident_list_counts_by_status(
    db: Session, project: Project, dataset: Dataset, user: UserRead
):
    dataset.last_profiled_at = NOW - timedelta(hours=9)
    db.commit()
    _policy(db, project, dataset, user, minutes=60)
    check_freshness(db, project.id, user, now=NOW)

    listing = list_incidents(db, project.id, user)
    assert listing.open_count == 1
    assert listing.items[0].dataset_name == "orders"

    resolve_incident(db, project.id, listing.items[0].id, None, user)
    assert list_incidents(db, project.id, user, status="resolved").resolved_count == 1


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
