"""Incidents: grouping repeated failures into one thing a person owns.

A rule that fails on twenty consecutive nightly runs is one problem, not twenty
notifications. Without grouping, the alert list becomes something people mute,
and a muted alert list is worse than none because it looks like coverage.

Grouping is by *fingerprint*: a stable string derived from what failed, not from
when. The same rule failing again lands on the same incident, bumps its count,
and updates one timeline entry rather than appending a new one each night.

Incidents also close themselves. A freshness breach that heals, or a rule that
passes again, resolves the incident automatically with a timeline entry saying
so -- otherwise the list fills with problems that stopped being problems and
nobody trusts it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger

from service_observability.models import Incident, IncidentEvent

SOURCE_KINDS = ("quality", "drift", "freshness", "anomaly", "workflow", "runtime")
STATUSES = ("open", "acknowledged", "resolved")
SEVERITIES = ("low", "medium", "high", "critical")
ACTIVE_STATUSES = ("open", "acknowledged")

EVENT_KINDS = (
    "opened",
    "recurred",
    "acknowledged",
    "assigned",
    "comment",
    "resolved",
    "reopened",
    "auto_resolved",
)

MAX_TIMELINE_EVENTS = 200

logger = get_logger(__name__)


def fingerprint_for(source_kind: str, *parts: Any) -> str:
    """A stable identity for a recurring problem.

    Deliberately excludes anything time-varying -- a run id or a timestamp in
    here would make every occurrence a new incident, which is the failure this
    whole module exists to prevent.
    """
    if source_kind not in SOURCE_KINDS:
        raise BadRequestError(f"Unknown incident source '{source_kind}'.")
    tail = ":".join(str(part) if part is not None else "-" for part in parts)
    return f"{source_kind}:{tail}" if tail else source_kind


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _next_sequence(db: Session, incident_id: uuid.UUID) -> int:
    highest = db.scalar(
        select(func.max(IncidentEvent.sequence)).where(IncidentEvent.incident_id == incident_id)
    )
    return int(highest or 0) + 1


def _add_event(
    db: Session,
    incident: Incident,
    *,
    kind: str,
    message: str,
    actor_user_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident.id,
        project_id=incident.project_id,
        sequence=_next_sequence(db, incident.id),
        kind=kind,
        message=message,
        actor_user_id=actor_user_id,
        data_json=data,
    )
    db.add(event)
    db.flush()
    return event


def _latest_event(db: Session, incident_id: uuid.UUID) -> IncidentEvent | None:
    return db.scalar(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.sequence.desc())
        .limit(1)
    )


def active_by_fingerprint(db: Session, fingerprint: str) -> list[Incident]:
    """Every open incident with this fingerprint, across all projects.

    A platform-wide condition (a dead worker) opens one incident per affected
    project; resolving it means finding them all, not one project at a time.
    """
    return list(
        db.scalars(
            select(Incident).where(
                Incident.fingerprint == fingerprint,
                Incident.status.in_(ACTIVE_STATUSES),
            )
        ).all()
    )


def find_active(db: Session, project_id: uuid.UUID, fingerprint: str) -> Incident | None:
    return db.scalar(
        select(Incident)
        .where(
            Incident.project_id == project_id,
            Incident.fingerprint == fingerprint,
            Incident.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Incident.opened_at.desc())
        .limit(1)
    )


def report(
    db: Session,
    *,
    project_id: uuid.UUID,
    fingerprint: str,
    title: str,
    summary: str | None,
    source_kind: str,
    source_id: str | None = None,
    severity: str = "high",
    dataset_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Incident:
    """Open an incident, or record another occurrence of an open one."""
    if severity not in SEVERITIES:
        raise BadRequestError(f"Unknown incident severity '{severity}'.")
    moment = _now(now)

    existing = find_active(db, project_id, fingerprint)
    if existing is not None:
        existing.occurrence_count += 1
        existing.last_seen_at = moment
        existing.summary = summary or existing.summary
        # Escalate but never quietly de-escalate: a problem that got worse once
        # stays at its worst known severity until someone closes it.
        if SEVERITIES.index(severity) > SEVERITIES.index(existing.severity):
            existing.severity = severity
        if context:
            existing.context_json = context

        latest = _latest_event(db, existing.id)
        if latest is not None and latest.kind == "recurred":
            # Collapse consecutive recurrences into one line rather than
            # producing a timeline nobody can read.
            latest.message = (
                f"Seen {existing.occurrence_count} times, most recently "
                f"{moment.strftime('%Y-%m-%d %H:%M UTC')}."
            )
            latest.data_json = {"occurrence_count": existing.occurrence_count}
        else:
            _add_event(
                db,
                existing,
                kind="recurred",
                message=(
                    f"Seen {existing.occurrence_count} times, most recently "
                    f"{moment.strftime('%Y-%m-%d %H:%M UTC')}."
                ),
                data={"occurrence_count": existing.occurrence_count},
            )
        db.flush()
        return existing

    incident = Incident(
        project_id=project_id,
        fingerprint=fingerprint,
        title=title[:200],
        summary=summary,
        source_kind=source_kind,
        source_id=source_id,
        severity=severity,
        status="open",
        dataset_id=dataset_id,
        workflow_id=workflow_id,
        opened_at=moment,
        last_seen_at=moment,
        occurrence_count=1,
        context_json=context,
    )
    db.add(incident)
    db.flush()
    _add_event(db, incident, kind="opened", message=summary or title)
    _notify_owner(db, incident)
    db.flush()
    return incident


def _notify_owner(db: Session, incident: Incident) -> None:
    """Tell someone an incident opened.

    An incident nobody is told about is a list nobody opens. Only the *first*
    occurrence notifies -- a nightly failure that has already been reported
    should not send a message every night, which is how people learn to filter
    the whole channel away.

    Best effort: failing to notify must never roll back the incident itself.
    """
    try:
        from service_notifications.service import create_user_notification
        from service_projects.models import Project

        project = db.get(Project, incident.project_id)
        if project is None or project.owner_user_id is None:
            return

        create_user_notification(
            db,
            user_id=project.owner_user_id,
            project_id=incident.project_id,
            type="incident",
            level="error" if incident.severity in ("critical", "high") else "warning",
            title=incident.title,
            message=incident.summary or "An automated check failed.",
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("incident_notify_failed incident_id=%s", incident.id)


def auto_resolve(
    db: Session,
    *,
    project_id: uuid.UUID,
    fingerprint: str,
    message: str,
    now: datetime | None = None,
) -> Incident | None:
    """Close an incident because the condition that opened it went away."""
    incident = find_active(db, project_id, fingerprint)
    if incident is None:
        return None

    incident.status = "resolved"
    incident.resolved_at = _now(now)
    incident.resolution_note = message
    _add_event(db, incident, kind="auto_resolved", message=message)
    db.flush()
    return incident


def get_incident(db: Session, project_id: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    incident = db.scalar(
        select(Incident).where(Incident.id == incident_id, Incident.project_id == project_id)
    )
    if incident is None:
        raise NotFoundError("Incident not found.")
    return incident


def acknowledge(
    db: Session,
    incident: Incident,
    *,
    actor_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> Incident:
    if incident.status == "resolved":
        raise BadRequestError("This incident is already resolved.")
    if incident.status == "acknowledged":
        return incident
    incident.status = "acknowledged"
    incident.acknowledged_at = _now(now)
    _add_event(
        db, incident, kind="acknowledged", message="Acknowledged.", actor_user_id=actor_user_id
    )
    db.flush()
    return incident


def assign(
    db: Session,
    incident: Incident,
    *,
    assignee_user_id: uuid.UUID | None,
    assignee_name: str | None,
    actor_user_id: uuid.UUID | None,
) -> Incident:
    incident.assignee_user_id = assignee_user_id
    message = f"Assigned to {assignee_name}." if assignee_name else "Assignee cleared."
    _add_event(db, incident, kind="assigned", message=message, actor_user_id=actor_user_id)
    db.flush()
    return incident


def resolve(
    db: Session,
    incident: Incident,
    *,
    note: str | None,
    actor_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> Incident:
    if incident.status == "resolved":
        raise BadRequestError("This incident is already resolved.")
    incident.status = "resolved"
    incident.resolved_at = _now(now)
    incident.resolution_note = note
    _add_event(
        db,
        incident,
        kind="resolved",
        message=note or "Resolved.",
        actor_user_id=actor_user_id,
    )
    db.flush()
    return incident


def reopen(
    db: Session, incident: Incident, *, reason: str | None, actor_user_id: uuid.UUID | None
) -> Incident:
    if incident.status != "resolved":
        raise BadRequestError("This incident is not resolved.")
    incident.status = "open"
    incident.resolved_at = None
    incident.resolution_note = None
    _add_event(
        db,
        incident,
        kind="reopened",
        message=reason or "Reopened.",
        actor_user_id=actor_user_id,
    )
    db.flush()
    return incident


def comment(
    db: Session, incident: Incident, *, message: str, actor_user_id: uuid.UUID | None
) -> IncidentEvent:
    text = message.strip()
    if not text:
        raise BadRequestError("A comment cannot be empty.")
    event = _add_event(db, incident, kind="comment", message=text, actor_user_id=actor_user_id)
    db.flush()
    return event


def timeline(db: Session, incident_id: uuid.UUID, *, limit: int = MAX_TIMELINE_EVENTS) -> list[IncidentEvent]:
    return list(
        db.scalars(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.sequence.asc())
            .limit(limit)
        ).all()
    )


def open_count(db: Session, project_id: uuid.UUID | None = None) -> int:
    statement = select(func.count(Incident.id)).where(Incident.status.in_(ACTIVE_STATUSES))
    if project_id is not None:
        statement = statement.where(Incident.project_id == project_id)
    return db.scalar(statement) or 0
