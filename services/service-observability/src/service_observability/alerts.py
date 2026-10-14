"""Alerts on a dataset's measures (adoption-readiness A8, Y5).

A person draws a line a measure should not cross: the row count above or
below a number, a column's null rate above a share, or any measure changing
by more than a share since the last time it was recorded. Measures are
recorded whenever a dataset gets new data (an upload, an import, a recipe
run, a workflow, a rollback) and when someone records them by hand; each
time, this module checks the dataset's alerts against them.

An alert says so when it crosses its line and again when it comes back, not
on every run while it stays over: a line that is crossed every night and
reported every night is soon ignored. Each crossing is written as an event
in the same transaction as the measures, and the background worker sends it
once that transaction has committed (`send_due`), to the project's people
and to its alert targets that take "A measure crossed its alert".
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger

from service_observability.metrics import (
    ALL_METRICS,
    COLUMN_METRICS,
    DATASET_METRICS,
    METRIC_UNITS,
    MetricSample,
    describe,
    format_value,
)
from service_observability.models import DatasetMetric, MetricAlert, MetricAlertEvent
from service_observability.schemas import (
    MetricAlertCreate,
    MetricAlertEventRead,
    MetricAlertListResponse,
    MetricAlertRead,
    MetricAlertUpdate,
)

logger = get_logger(__name__)

CONDITIONS = ("above", "below", "changes_by")
EVENT_TYPE = "metric_alert"
MAX_ALERTS_PER_DATASET = 50
MAX_CHANGE_PERCENTAGE = 10_000
RECENT_EVENTS = 20
# Who hears about an alert in the app, as for incidents.
ACTING_ROLES = ("operator", "editor", "admin")

Series = tuple[str, str | None]


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _percent(value: float) -> str:
    return f"{value:,.1f}".rstrip("0").rstrip(".") + "%"


def sentence(metric_key: str, column_name: str | None, condition: str, threshold: float) -> str:
    """"Alert when the row count is above 1,000", as the page lists it."""
    what = describe(metric_key, column_name)
    if condition == "changes_by":
        return f"Alert when the {what} changes by more than {_percent(threshold)} from one time to the next"
    word = "above" if condition == "above" else "below"
    return f"Alert when the {what} is {word} {format_value(metric_key, threshold)}"


def outside(condition: str, threshold: float, value: float, previous: float | None) -> bool | None:
    """Whether a value is past the line; None when it cannot be told yet (a
    change with nothing recorded before it)."""
    if condition == "above":
        return value > threshold
    if condition == "below":
        return value < threshold
    if previous is None:
        return None
    if previous == 0:
        return value != 0
    return abs(value - previous) / abs(previous) * 100 > threshold


def _words(alert: MetricAlert, dataset_name: str, kind: str, value: float, previous: float | None) -> tuple[str, str]:
    what = describe(alert.metric_key, alert.column_name)
    shown = format_value(alert.metric_key, value)
    if kind == "cleared":
        return (
            f"{dataset_name}: the {what} is back within its alert",
            f"In {dataset_name}, the {what} is {shown}, within its alert again. "
            f"{sentence(alert.metric_key, alert.column_name, alert.condition, alert.threshold)}.",
        )
    if alert.condition == "changes_by":
        before = format_value(alert.metric_key, previous if previous is not None else 0)
        if previous:
            change = _percent(abs(value - previous) / abs(previous) * 100)
            return (
                f"{dataset_name}: the {what} changed by {change}",
                f"In {dataset_name}, the {what} went from {before} to {shown}, a change of {change}, "
                f"more than the {_percent(alert.threshold)} its alert allows.",
            )
        return (
            f"{dataset_name}: the {what} changed from {before}",
            f"In {dataset_name}, the {what} went from {before} to {shown}.",
        )
    word = "above" if alert.condition == "above" else "below"
    line = format_value(alert.metric_key, alert.threshold)
    return (
        f"{dataset_name}: the {what} is {word} {line}",
        f"In {dataset_name}, the {what} is {shown}, {word} the {line} its alert allows.",
    )


def _judge(
    db: Session,
    alert: MetricAlert,
    *,
    dataset_name: str,
    value: float,
    previous: float | None,
    now: datetime,
) -> MetricAlertEvent | None:
    """Record a reading against an alert, and an event when it crossed or came back."""
    alert.last_value = value
    alert.last_checked_at = now
    past = outside(alert.condition, alert.threshold, value, previous)
    if past is None:
        return None
    state = "crossed" if past else "ok"
    if state == alert.state:
        return None
    alert.state = state
    kind = "crossed" if past else "cleared"
    title, message = _words(alert, dataset_name, kind, value, previous)
    event = MetricAlertEvent(
        project_id=alert.project_id,
        alert_id=alert.id,
        dataset_id=alert.dataset_id,
        kind=kind,
        value=value,
        previous_value=previous,
        title=title[:240],
        message=message,
        # The capture's own moment, so two events from one second keep their order.
        created_at=now,
    )
    db.add(event)
    return event


def _latest(db: Session, dataset_id: uuid.UUID, series: Series, *, count: int) -> list[float]:
    """The newest recorded values of one series, newest first."""
    key, column = series
    statement = select(DatasetMetric.value).where(
        DatasetMetric.dataset_id == dataset_id, DatasetMetric.metric_key == key
    )
    statement = statement.where(
        DatasetMetric.column_name.is_(None) if column is None else DatasetMetric.column_name == column
    )
    return list(db.scalars(statement.order_by(DatasetMetric.captured_at.desc()).limit(count)).all())


def previous_values(db: Session, dataset_id: uuid.UUID) -> dict[Series, float]:
    """For each series an enabled alert watches, its last recorded value.

    Read before a new capture is written, so a change is measured against the
    time before. Empty, and no queries beyond one, when the dataset has no alerts.
    """
    alerts = db.scalars(
        select(MetricAlert).where(MetricAlert.dataset_id == dataset_id, MetricAlert.enabled.is_(True))
    ).all()
    found: dict[Series, float] = {}
    for alert in alerts:
        series = (alert.metric_key, alert.column_name)
        if series not in found:
            latest = _latest(db, dataset_id, series, count=1)
            if latest:
                found[series] = latest[0]
    return found


def check_alerts(
    db: Session,
    *,
    dataset_id: uuid.UUID,
    samples: list[MetricSample],
    previous: dict[Series, float],
    now: datetime | None = None,
) -> int:
    """Check a dataset's enabled alerts against a capture. Returns how many crossed or came back."""
    alerts = db.scalars(
        select(MetricAlert).where(MetricAlert.dataset_id == dataset_id, MetricAlert.enabled.is_(True))
    ).all()
    if not alerts:
        return 0
    values = {(sample.metric_key, sample.column_name): sample.value for sample in samples}
    dataset = db.get(Dataset, dataset_id)
    name = dataset.name if dataset is not None else "A dataset"
    moment = _now(now)
    changed = 0
    for alert in alerts:
        series = (alert.metric_key, alert.column_name)
        if series not in values:
            continue
        if _judge(db, alert, dataset_name=name, value=values[series], previous=previous.get(series), now=moment):
            changed += 1
    return changed


# --------------------------------------------------------------------------
# Sending, from the background worker
# --------------------------------------------------------------------------


def send_due(db: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Send the alert events written since the last time, once each.

    Each event is claimed with a conditional update before it is sent, so two
    workers never send the same one; a failure to reach someone is logged and
    not tried again here (webhooks keep their own retries).
    """
    from service_access.models import ProjectMembership
    from service_notifications.external_dispatch import dispatch_external_notifications
    from service_notifications.service import create_user_notification
    from service_projects.models import Project

    moment = _now(now)
    pending = db.scalars(
        select(MetricAlertEvent).where(MetricAlertEvent.sent_at.is_(None)).order_by(MetricAlertEvent.created_at).limit(limit)
    ).all()
    sent = 0
    for event in pending:
        claimed = db.execute(
            update(MetricAlertEvent)
            .where(MetricAlertEvent.id == event.id, MetricAlertEvent.sent_at.is_(None))
            .values(sent_at=moment)
        )
        db.commit()
        if claimed.rowcount != 1:
            continue
        try:
            level = "warning" if event.kind == "crossed" else "info"
            project = db.get(Project, event.project_id)
            people = {project.owner_user_id} if project is not None and project.owner_user_id else set()
            people.update(
                db.scalars(
                    select(ProjectMembership.user_id).where(
                        ProjectMembership.project_id == event.project_id,
                        ProjectMembership.role.in_(ACTING_ROLES),
                    )
                ).all()
            )
            for user_id in sorted(people, key=str):
                create_user_notification(
                    db,
                    user_id=user_id,
                    project_id=event.project_id,
                    type=EVENT_TYPE,
                    level=level,
                    title=event.title,
                    message=event.message,
                    related_dataset_id=event.dataset_id,
                )
            dispatch_external_notifications(
                db,
                project_id=event.project_id,
                event_type=EVENT_TYPE,
                title=event.title,
                message=event.message,
                level=level,
            )
            db.commit()
            sent += 1
        except Exception:  # noqa: BLE001 - one event must not stop the rest
            db.rollback()
            logger.exception("metric_alert_send_failed event_id=%s", event.id)
    return sent


# --------------------------------------------------------------------------
# Managing alerts
# --------------------------------------------------------------------------


def _dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id))
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def _columns(dataset: Dataset) -> list[str]:
    for source in (dataset.schema_json, dataset.profile_json):
        columns = source.get("columns") if isinstance(source, dict) else None
        if isinstance(columns, list):
            names = [entry.get("name") for entry in columns if isinstance(entry, dict)]
            return [name for name in names if isinstance(name, str)]
    return []


def _check_line(metric_key: str, condition: str, threshold: float) -> None:
    if not math.isfinite(threshold):
        raise BadRequestError("The value needs to be a number.")
    if condition == "changes_by":
        if not 0 < threshold <= MAX_CHANGE_PERCENTAGE:
            raise BadRequestError(f"A change needs to be more than 0% and at most {MAX_CHANGE_PERCENTAGE:,}%.")
    elif METRIC_UNITS.get(metric_key) == "%" and not 0 <= threshold <= 100:
        raise BadRequestError(f"The {describe(metric_key)} is a share, so the value needs to be between 0 and 100.")
    elif metric_key in ("row_count", "column_count", "unique_count") and threshold < 0:
        raise BadRequestError(f"The {describe(metric_key)} is never below 0.")


def _read(alert: MetricAlert) -> MetricAlertRead:
    return MetricAlertRead(
        id=alert.id,
        dataset_id=alert.dataset_id,
        metric_key=alert.metric_key,
        column_name=alert.column_name,
        condition=alert.condition,  # type: ignore[arg-type]
        threshold=alert.threshold,
        enabled=alert.enabled,
        state=alert.state,  # type: ignore[arg-type]
        sentence=sentence(alert.metric_key, alert.column_name, alert.condition, alert.threshold),
        last_value=alert.last_value,
        last_checked_at=alert.last_checked_at,
        created_at=alert.created_at,
    )


def _event_read(event: MetricAlertEvent) -> MetricAlertEventRead:
    return MetricAlertEventRead(
        id=event.id,
        alert_id=event.alert_id,
        kind=event.kind,  # type: ignore[arg-type]
        value=event.value,
        previous_value=event.previous_value,
        title=event.title,
        message=event.message,
        created_at=event.created_at,
        sent_at=event.sent_at,
    )


def _judge_latest(db: Session, alert: MetricAlert, dataset: Dataset) -> None:
    """Hold a new or changed alert against the measures already recorded, so
    one made past its line says so now rather than at the next run."""
    if not alert.enabled:
        return
    newest = _latest(db, dataset.id, (alert.metric_key, alert.column_name), count=2)
    if newest:
        _judge(
            db,
            alert,
            dataset_name=dataset.name,
            value=newest[0],
            previous=newest[1] if len(newest) > 1 else None,
            now=_now(),
        )


def list_alerts(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> MetricAlertListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    _dataset(db, project_id, dataset_id)
    alerts = db.scalars(
        select(MetricAlert).where(MetricAlert.dataset_id == dataset_id).order_by(MetricAlert.created_at)
    ).all()
    events = db.scalars(
        select(MetricAlertEvent)
        .where(MetricAlertEvent.dataset_id == dataset_id)
        .order_by(MetricAlertEvent.created_at.desc())
        .limit(RECENT_EVENTS)
    ).all()
    return MetricAlertListResponse(items=[_read(alert) for alert in alerts], events=[_event_read(e) for e in events])


def create_alert(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, payload: MetricAlertCreate, current_user: UserRead
) -> MetricAlertRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    if payload.metric_key not in ALL_METRICS:
        raise BadRequestError(f"Pipewright does not record “{payload.metric_key}”. Choose one of the measures listed.")
    column = (payload.column_name or "").strip() or None
    if payload.metric_key in DATASET_METRICS and column is not None:
        raise BadRequestError(f"The {describe(payload.metric_key)} is the whole dataset's, so it takes no column.")
    if payload.metric_key in COLUMN_METRICS:
        if column is None:
            raise BadRequestError(f"Choose the column whose {describe(payload.metric_key)} to watch.")
        if column not in _columns(dataset):
            raise BadRequestError(f"{dataset.name} has no column “{column}”.")
    _check_line(payload.metric_key, payload.condition, payload.threshold)
    count = len(db.scalars(select(MetricAlert.id).where(MetricAlert.dataset_id == dataset_id)).all())
    if count >= MAX_ALERTS_PER_DATASET:
        raise BadRequestError(f"A dataset can have up to {MAX_ALERTS_PER_DATASET} alerts. Remove one first.")

    alert = MetricAlert(
        project_id=project_id,
        dataset_id=dataset_id,
        metric_key=payload.metric_key,
        column_name=column,
        condition=payload.condition,
        threshold=payload.threshold,
        created_by_user_id=current_user.id,
    )
    db.add(alert)
    db.flush()
    _judge_latest(db, alert, dataset)
    db.commit()
    db.refresh(alert)
    return _read(alert)


def _alert(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, alert_id: uuid.UUID) -> MetricAlert:
    alert = db.scalar(
        select(MetricAlert).where(
            MetricAlert.id == alert_id, MetricAlert.dataset_id == dataset_id, MetricAlert.project_id == project_id
        )
    )
    if alert is None:
        raise NotFoundError("Alert not found.")
    return alert


def update_alert(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    alert_id: uuid.UUID,
    payload: MetricAlertUpdate,
    current_user: UserRead,
) -> MetricAlertRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _dataset(db, project_id, dataset_id)
    alert = _alert(db, project_id, dataset_id, alert_id)
    condition = payload.condition or alert.condition
    threshold = alert.threshold if payload.threshold is None else payload.threshold
    _check_line(alert.metric_key, condition, threshold)
    moved = condition != alert.condition or threshold != alert.threshold
    alert.condition, alert.threshold = condition, threshold
    if payload.enabled is not None and payload.enabled != alert.enabled:
        alert.enabled = payload.enabled
        moved = True
    if moved:
        # A changed line starts afresh against the newest measures.
        alert.state = "ok"
        _judge_latest(db, alert, dataset)
    db.commit()
    db.refresh(alert)
    return _read(alert)


def delete_alert(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, alert_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    db.delete(_alert(db, project_id, dataset_id, alert_id))
    db.commit()
