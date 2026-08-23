"""Metric history, anomaly scans, freshness checks, and the incident list."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_observability import incidents as incident_ops
from service_observability.anomaly import (
    DEFAULT_SENSITIVITY,
    MIN_HISTORY,
    detect_anomaly,
    severity_for,
)
from service_observability.freshness import evaluate_freshness, humanise_minutes
from service_observability.metrics import (
    METRIC_UNITS,
    describe,
    metrics_from_profile,
)
from service_observability.models import DatasetMetric, FreshnessPolicy, Incident
from service_observability.schemas import (
    AnomalyRead,
    AnomalyScanResponse,
    FreshnessCheckItem,
    FreshnessCheckResponse,
    FreshnessPolicyCreate,
    FreshnessPolicyListResponse,
    FreshnessPolicyRead,
    FreshnessPolicyUpdate,
    IncidentCommentRequest,
    IncidentDetail,
    IncidentEventRead,
    IncidentListResponse,
    IncidentRead,
    MetricCaptureResponse,
    MetricHistoryResponse,
    MetricPoint,
    MetricSeries,
)

# Enough to see a trend without loading a year of nightly runs into a chart.
DEFAULT_HISTORY_LIMIT = 60
MAX_HISTORY_LIMIT = 365
# Anomaly scans need the current value plus a baseline behind it.
ANOMALY_WINDOW = 40


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _get_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def record_dataset_metrics(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    profile: dict[str, Any] | None,
    workflow_run_id: uuid.UUID | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    logical_date: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """Write one profile's worth of measurements to the history.

    Returns how many were recorded. Called from run paths, so it never raises
    on an empty or malformed profile -- a missing measurement should not fail a
    run that otherwise worked.
    """
    samples = metrics_from_profile(profile)
    if not samples:
        return 0

    captured_at = _now(now)
    db.add_all(
        [
            DatasetMetric(
                project_id=project_id,
                dataset_id=dataset_id,
                workflow_run_id=workflow_run_id,
                pipeline_run_id=pipeline_run_id,
                metric_key=sample.metric_key,
                column_name=sample.column_name,
                value=sample.value,
                captured_at=captured_at,
                logical_date=logical_date,
            )
            for sample in samples
        ]
    )
    db.flush()
    return len(samples)


def capture_dataset_metrics(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> MetricCaptureResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)
    if not isinstance(dataset.profile_json, dict) or not dataset.profile_json:
        raise BadRequestError("This dataset has not been profiled yet, so there is nothing to record.")

    captured_at = _now()
    count = record_dataset_metrics(
        db,
        project_id=project_id,
        dataset_id=dataset_id,
        profile=dataset.profile_json,
        now=captured_at,
    )
    db.commit()
    return MetricCaptureResponse(
        dataset_id=dataset_id, metrics_recorded=count, captured_at=captured_at
    )


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def _series_rows(
    db: Session,
    dataset_id: uuid.UUID,
    *,
    metric_key: str | None,
    column_name: str | None,
    limit: int,
) -> list[DatasetMetric]:
    statement = select(DatasetMetric).where(DatasetMetric.dataset_id == dataset_id)
    if metric_key:
        statement = statement.where(DatasetMetric.metric_key == metric_key)
    if column_name is not None:
        statement = statement.where(DatasetMetric.column_name == column_name)
    statement = statement.order_by(DatasetMetric.captured_at.desc()).limit(limit)
    return list(db.scalars(statement).all())


def get_metric_history(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    metric_key: str | None = None,
    column_name: str | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> MetricHistoryResponse:
    ensure_owned_project(db, project_id, current_user.id)
    _get_dataset(db, project_id, dataset_id)

    limit = max(1, min(limit, MAX_HISTORY_LIMIT))
    # One query for every series, then grouped in memory: a query per metric
    # would be dozens of round trips for one chart page.
    rows = _series_rows(
        db,
        dataset_id,
        metric_key=metric_key,
        column_name=column_name,
        limit=limit * 40 if metric_key is None else limit,
    )

    grouped: dict[tuple[str, str | None], list[DatasetMetric]] = {}
    for row in rows:
        grouped.setdefault((row.metric_key, row.column_name), []).append(row)

    series: list[MetricSeries] = []
    for (key, column), entries in sorted(grouped.items(), key=lambda item: (item[0][1] or "", item[0][0])):
        ordered = sorted(entries, key=lambda entry: entry.captured_at)[-limit:]
        values = [entry.value for entry in ordered]
        latest = values[-1] if values else None
        previous = values[-2] if len(values) > 1 else None
        change = None
        if latest is not None and previous not in (None, 0):
            change = round((latest - previous) / abs(previous) * 100, 2)

        series.append(
            MetricSeries(
                metric_key=key,
                column_name=column,
                label=describe(key, column),
                unit=METRIC_UNITS.get(key),
                points=[
                    MetricPoint(
                        value=entry.value,
                        captured_at=entry.captured_at,
                        logical_date=entry.logical_date,
                        workflow_run_id=entry.workflow_run_id,
                    )
                    for entry in ordered
                ],
                latest=latest,
                previous=previous,
                change_percentage=change,
            )
        )

    return MetricHistoryResponse(dataset_id=dataset_id, series=series)


# --------------------------------------------------------------------------
# Anomalies
# --------------------------------------------------------------------------


def scan_dataset_anomalies(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    sensitivity: str = DEFAULT_SENSITIVITY,
    open_incidents: bool = False,
) -> AnomalyScanResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, dataset_id)

    rows = _series_rows(
        db, dataset_id, metric_key=None, column_name=None, limit=ANOMALY_WINDOW * 60
    )
    grouped: dict[tuple[str, str | None], list[DatasetMetric]] = {}
    for row in rows:
        grouped.setdefault((row.metric_key, row.column_name), []).append(row)

    results: list[AnomalyRead] = []
    for (key, column), entries in grouped.items():
        ordered = sorted(entries, key=lambda entry: entry.captured_at)[-ANOMALY_WINDOW:]
        if not ordered:
            continue
        current = ordered[-1].value
        # The current value must not be part of its own baseline.
        history = [entry.value for entry in ordered[:-1]]
        verdict = detect_anomaly(
            metric_key=key,
            value=current,
            history=history,
            column_name=column,
            sensitivity=sensitivity,
        )
        results.append(
            AnomalyRead(
                metric_key=key,
                column_name=column,
                label=describe(key, column),
                value=verdict.value,
                baseline=verdict.baseline,
                score=verdict.score,
                status=verdict.status,
                direction=verdict.direction,
                sample_size=verdict.sample_size,
                severity=severity_for(verdict),
                explanation=verdict.explanation,
            )
        )

        if open_incidents and verdict.is_anomalous:
            fingerprint = incident_ops.fingerprint_for("anomaly", dataset_id, key, column)
            incident_ops.report(
                db,
                project_id=project_id,
                fingerprint=fingerprint,
                title=f"{describe(key, column).capitalize()} looks wrong in {dataset.name}",
                summary=verdict.explanation,
                source_kind="anomaly",
                source_id=key,
                severity=severity_for(verdict),
                dataset_id=dataset_id,
                context=verdict.to_dict(),
            )

    anomalous = [result for result in results if result.status == "anomalous"]
    without_baseline = [result for result in results if result.status == "no_baseline"]

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    anomalous.sort(key=lambda result: (order[result.severity], result.label))

    if open_incidents:
        db.commit()

    if anomalous:
        summary = (
            f"{len(anomalous)} of {len(results)} tracked metrics are outside their usual range."
        )
    elif results and len(without_baseline) == len(results):
        summary = (
            f"No baselines yet: each metric needs {MIN_HISTORY} runs of history before "
            "normal can be established."
        )
    elif results:
        summary = f"All {len(results)} tracked metrics are in line with their history."
    else:
        summary = "No metrics have been recorded for this dataset yet."

    return AnomalyScanResponse(
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        sensitivity=sensitivity,  # type: ignore[arg-type]
        anomalies=anomalous + [result for result in results if result.status != "anomalous"],
        checked_count=len(results),
        summary=summary,
    )


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------


def _dataset_updated_at(dataset: Dataset) -> datetime | None:
    return _as_utc(dataset.last_profiled_at) or _as_utc(dataset.updated_at)


def _policy_read(policy: FreshnessPolicy, dataset_name: str | None) -> FreshnessPolicyRead:
    return FreshnessPolicyRead(
        id=policy.id,
        project_id=policy.project_id,
        dataset_id=policy.dataset_id,
        dataset_name=dataset_name,
        max_age_minutes=policy.max_age_minutes,
        severity=policy.severity,  # type: ignore[arg-type]
        enabled=policy.enabled,
        last_checked_at=policy.last_checked_at,
        last_status=policy.last_status,
        last_age_minutes=policy.last_age_minutes,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def list_freshness_policies(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> FreshnessPolicyListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    policies = db.scalars(
        select(FreshnessPolicy)
        .where(FreshnessPolicy.project_id == project_id)
        .order_by(FreshnessPolicy.created_at.desc())
    ).all()
    names = _dataset_names(db, [policy.dataset_id for policy in policies])
    return FreshnessPolicyListResponse(
        items=[_policy_read(policy, names.get(policy.dataset_id)) for policy in policies]
    )


def _dataset_names(db: Session, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not dataset_ids:
        return {}
    rows = db.execute(
        select(Dataset.id, Dataset.name).where(Dataset.id.in_(dataset_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


def create_freshness_policy(
    db: Session, project_id: uuid.UUID, payload: FreshnessPolicyCreate, current_user: UserRead
) -> FreshnessPolicyRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, payload.dataset_id)

    existing = db.scalar(
        select(FreshnessPolicy).where(FreshnessPolicy.dataset_id == payload.dataset_id)
    )
    if existing is not None:
        raise BadRequestError("This dataset already has a freshness policy; edit that one instead.")

    policy = FreshnessPolicy(
        project_id=project_id,
        dataset_id=payload.dataset_id,
        max_age_minutes=payload.max_age_minutes,
        severity=payload.severity,
        enabled=payload.enabled,
        owner_user_id=current_user.id,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return _policy_read(policy, dataset.name)


def update_freshness_policy(
    db: Session,
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    payload: FreshnessPolicyUpdate,
    current_user: UserRead,
) -> FreshnessPolicyRead:
    ensure_owned_project(db, project_id, current_user.id)
    policy = db.scalar(
        select(FreshnessPolicy).where(
            FreshnessPolicy.id == policy_id, FreshnessPolicy.project_id == project_id
        )
    )
    if policy is None:
        raise NotFoundError("Freshness policy not found.")

    if payload.max_age_minutes is not None:
        policy.max_age_minutes = payload.max_age_minutes
    if payload.severity is not None:
        policy.severity = payload.severity
    if payload.enabled is not None:
        policy.enabled = payload.enabled

    db.commit()
    db.refresh(policy)
    names = _dataset_names(db, [policy.dataset_id])
    return _policy_read(policy, names.get(policy.dataset_id))


def delete_freshness_policy(
    db: Session, project_id: uuid.UUID, policy_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    policy = db.scalar(
        select(FreshnessPolicy).where(
            FreshnessPolicy.id == policy_id, FreshnessPolicy.project_id == project_id
        )
    )
    if policy is None:
        raise NotFoundError("Freshness policy not found.")
    db.delete(policy)
    db.commit()


# How often an unattended sweep re-checks a policy, as a fraction of its own
# limit. Checking a six-hour promise every thirty seconds would make one stale
# dataset look like it failed thousands of times.
_SWEEP_FRACTION = 4
_MIN_SWEEP_MINUTES = 1
_MAX_SWEEP_MINUTES = 60


def _sweep_interval_minutes(policy: FreshnessPolicy) -> float:
    quarter = policy.max_age_minutes / _SWEEP_FRACTION
    return max(_MIN_SWEEP_MINUTES, min(quarter, _MAX_SWEEP_MINUTES))


def _policy_is_due(policy: FreshnessPolicy, now: datetime) -> bool:
    if policy.last_checked_at is None:
        return True
    checked = _as_utc(policy.last_checked_at)
    assert checked is not None
    elapsed_minutes = (now - checked).total_seconds() / 60
    return elapsed_minutes >= _sweep_interval_minutes(policy)


def check_freshness(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead | None = None,
    *,
    now: datetime | None = None,
    commit: bool = True,
    due_only: bool = False,
) -> FreshnessCheckResponse:
    """Evaluate every enabled policy, opening and closing incidents as needed.

    ``due_only`` is for the unattended sweep: it skips policies checked
    recently, so a worker ticking every thirty seconds does not inflate an
    incident's occurrence count into nonsense.
    """
    if current_user is not None:
        ensure_owned_project(db, project_id, current_user.id)

    moment = _now(now)
    policies = db.scalars(
        select(FreshnessPolicy).where(
            FreshnessPolicy.project_id == project_id, FreshnessPolicy.enabled.is_(True)
        )
    ).all()
    if due_only:
        policies = [policy for policy in policies if _policy_is_due(policy, moment)]

    datasets = _datasets_by_id(db, [policy.dataset_id for policy in policies])
    items: list[FreshnessCheckItem] = []
    opened = resolved = stale = 0

    for policy in policies:
        dataset = datasets.get(policy.dataset_id)
        if dataset is None:
            continue

        verdict = evaluate_freshness(
            last_updated_at=_dataset_updated_at(dataset),
            max_age_minutes=policy.max_age_minutes,
            now=moment,
        )
        policy.last_checked_at = moment
        policy.last_status = verdict.status
        policy.last_age_minutes = verdict.age_minutes

        fingerprint = incident_ops.fingerprint_for("freshness", policy.dataset_id)
        incident_id: uuid.UUID | None = None

        if verdict.is_breach:
            stale += 1
            before = incident_ops.find_active(db, project_id, fingerprint)
            incident = incident_ops.report(
                db,
                project_id=project_id,
                fingerprint=fingerprint,
                title=f"{dataset.name} is stale",
                summary=verdict.explanation,
                source_kind="freshness",
                source_id=str(policy.id),
                severity=policy.severity,
                dataset_id=policy.dataset_id,
                context=verdict.to_dict(),
                now=moment,
            )
            incident_id = incident.id
            if before is None:
                opened += 1
        else:
            closed = incident_ops.auto_resolve(
                db,
                project_id=project_id,
                fingerprint=fingerprint,
                message=(
                    f"{dataset.name} is fresh again"
                    + (
                        f" ({humanise_minutes(verdict.age_minutes)} old)."
                        if verdict.age_minutes is not None
                        else "."
                    )
                ),
                now=moment,
            )
            if closed is not None:
                resolved += 1

        items.append(
            FreshnessCheckItem(
                dataset_id=policy.dataset_id,
                dataset_name=dataset.name,
                status=verdict.status,  # type: ignore[arg-type]
                age_minutes=verdict.age_minutes,
                max_age_minutes=verdict.max_age_minutes,
                overdue_minutes=verdict.overdue_minutes,
                explanation=verdict.explanation,
                incident_id=incident_id,
            )
        )

    if commit:
        db.commit()

    return FreshnessCheckResponse(
        checked=len(items),
        stale=stale,
        incidents_opened=opened,
        incidents_resolved=resolved,
        items=items,
    )


def _datasets_by_id(db: Session, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, Dataset]:
    if not dataset_ids:
        return {}
    rows = db.scalars(select(Dataset).where(Dataset.id.in_(dataset_ids))).all()
    return {dataset.id: dataset for dataset in rows}


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------


def _incident_read(
    incident: Incident, dataset_name: str | None, assignee_name: str | None
) -> IncidentRead:
    return IncidentRead(
        id=incident.id,
        project_id=incident.project_id,
        title=incident.title,
        summary=incident.summary,
        fingerprint=incident.fingerprint,
        source_kind=incident.source_kind,  # type: ignore[arg-type]
        source_id=incident.source_id,
        severity=incident.severity,  # type: ignore[arg-type]
        status=incident.status,  # type: ignore[arg-type]
        dataset_id=incident.dataset_id,
        dataset_name=dataset_name,
        workflow_id=incident.workflow_id,
        assignee_user_id=incident.assignee_user_id,
        assignee_name=assignee_name,
        opened_at=incident.opened_at,
        last_seen_at=incident.last_seen_at,
        acknowledged_at=incident.acknowledged_at,
        resolved_at=incident.resolved_at,
        resolution_note=incident.resolution_note,
        occurrence_count=incident.occurrence_count,
        context_json=incident.context_json,
    )


def _user_names(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = [user_id for user_id in user_ids if user_id is not None]
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(ids))).all()
    return {row[0]: row[1] for row in rows}


def list_incidents(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> IncidentListResponse:
    ensure_owned_project(db, project_id, current_user.id)

    statement = select(Incident).where(Incident.project_id == project_id)
    if status:
        statement = statement.where(Incident.status == status)
    if severity:
        statement = statement.where(Incident.severity == severity)
    rows = list(
        db.scalars(
            statement.order_by(Incident.last_seen_at.desc()).limit(max(1, min(limit, 500)))
        ).all()
    )

    dataset_names = _dataset_names(db, [row.dataset_id for row in rows if row.dataset_id])
    user_names = _user_names(db, [row.assignee_user_id for row in rows if row.assignee_user_id])

    counts = dict(
        db.execute(
            select(Incident.status, func.count(Incident.id))
            .where(Incident.project_id == project_id)
            .group_by(Incident.status)
        ).all()
    )

    return IncidentListResponse(
        items=[
            _incident_read(
                row,
                dataset_names.get(row.dataset_id) if row.dataset_id else None,
                user_names.get(row.assignee_user_id) if row.assignee_user_id else None,
            )
            for row in rows
        ],
        open_count=int(counts.get("open", 0)),
        acknowledged_count=int(counts.get("acknowledged", 0)),
        resolved_count=int(counts.get("resolved", 0)),
    )


def get_incident_detail(
    db: Session, project_id: uuid.UUID, incident_id: uuid.UUID, current_user: UserRead
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)
    events = incident_ops.timeline(db, incident_id)

    dataset_names = _dataset_names(db, [incident.dataset_id] if incident.dataset_id else [])
    actor_ids = [event.actor_user_id for event in events if event.actor_user_id]
    if incident.assignee_user_id:
        actor_ids.append(incident.assignee_user_id)
    names = _user_names(db, actor_ids)

    base = _incident_read(
        incident,
        dataset_names.get(incident.dataset_id) if incident.dataset_id else None,
        names.get(incident.assignee_user_id) if incident.assignee_user_id else None,
    )
    return IncidentDetail(
        **base.model_dump(),
        events=[
            IncidentEventRead(
                id=event.id,
                sequence=event.sequence,
                kind=event.kind,
                message=event.message,
                actor_user_id=event.actor_user_id,
                actor_name=names.get(event.actor_user_id) if event.actor_user_id else None,
                data_json=event.data_json,
                created_at=event.created_at,
            )
            for event in events
        ],
    )


def _reload_detail(
    db: Session, project_id: uuid.UUID, incident_id: uuid.UUID, current_user: UserRead
) -> IncidentDetail:
    db.commit()
    return get_incident_detail(db, project_id, incident_id, current_user)


def acknowledge_incident(
    db: Session, project_id: uuid.UUID, incident_id: uuid.UUID, current_user: UserRead
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)
    incident_ops.acknowledge(db, incident, actor_user_id=current_user.id)
    return _reload_detail(db, project_id, incident_id, current_user)


def resolve_incident(
    db: Session,
    project_id: uuid.UUID,
    incident_id: uuid.UUID,
    note: str | None,
    current_user: UserRead,
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)
    incident_ops.resolve(db, incident, note=note, actor_user_id=current_user.id)
    return _reload_detail(db, project_id, incident_id, current_user)


def reopen_incident(
    db: Session,
    project_id: uuid.UUID,
    incident_id: uuid.UUID,
    note: str | None,
    current_user: UserRead,
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)
    incident_ops.reopen(db, incident, reason=note, actor_user_id=current_user.id)
    return _reload_detail(db, project_id, incident_id, current_user)


def assign_incident(
    db: Session,
    project_id: uuid.UUID,
    incident_id: uuid.UUID,
    assignee_user_id: uuid.UUID | None,
    current_user: UserRead,
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)

    name: str | None = None
    if assignee_user_id is not None:
        user = db.get(User, assignee_user_id)
        if user is None:
            raise NotFoundError("User not found.")
        name = user.username

    incident_ops.assign(
        db,
        incident,
        assignee_user_id=assignee_user_id,
        assignee_name=name,
        actor_user_id=current_user.id,
    )
    return _reload_detail(db, project_id, incident_id, current_user)


def comment_on_incident(
    db: Session,
    project_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: IncidentCommentRequest,
    current_user: UserRead,
) -> IncidentDetail:
    ensure_owned_project(db, project_id, current_user.id)
    incident = incident_ops.get_incident(db, project_id, incident_id)
    incident_ops.comment(db, incident, message=payload.message, actor_user_id=current_user.id)
    return _reload_detail(db, project_id, incident_id, current_user)


def sweep_freshness(db: Session, *, now: datetime | None = None) -> int:
    """Check every project's freshness promises without anyone asking.

    Called from the worker tick. Freshness is the one check that has to run on
    a schedule by its nature: it asserts that something *did* happen, so
    nothing else will trigger it.
    """
    project_ids = db.scalars(
        select(FreshnessPolicy.project_id)
        .where(FreshnessPolicy.enabled.is_(True))
        .distinct()
    ).all()

    breaches = 0
    for project_id in project_ids:
        result = check_freshness(db, project_id, now=now, commit=False, due_only=True)
        breaches += result.stale
    if project_ids:
        db.commit()
    return breaches


def total_metrics(db: Session) -> int:
    return db.scalar(select(func.count(DatasetMetric.id))) or 0
