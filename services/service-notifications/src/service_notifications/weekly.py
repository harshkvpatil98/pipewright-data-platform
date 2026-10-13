"""A weekly round-up for the people who want the trend, not every event (A6, W6).

A project's email or Slack target subscribed to "weekly_summary" gets one
message a week: how many runs finished and failed, which incidents opened and
how many are still open, and how many datasets changed. The schedule ticker
calls `send_weekly_summaries` on every pass; a target is due when it has never
had a summary or its last one is a week old.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from service_notifications.at_rest_config import notification_target_config_for_internal_use
from service_notifications.constants import EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK
from service_notifications.models import ExternalNotificationTarget
from service_notifications.senders.email_sender import send_email_event_message
from service_notifications.senders.slack_sender import send_slack_event_message
from shared_python.logging import get_logger
from shared_python.words import count_of

logger = get_logger(__name__)

WEEK = timedelta(days=7)
EVENT = "weekly_summary"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def build_summary(db: Session, project_id, *, since: datetime, now: datetime) -> tuple[str, str]:
    """The title and the text of one project's summary for the period."""
    from service_datasets.models import Dataset, DatasetVersion
    from service_observability.models import Incident
    from service_pipeline_runs.models import PipelineRun
    from service_projects.models import Project

    project = db.get(Project, project_id)
    name = project.name if project is not None else "Your project"
    in_period = and_(PipelineRun.project_id == project_id, PipelineRun.created_at >= since, PipelineRun.created_at < now)
    runs = db.scalar(select(func.count(PipelineRun.id)).where(in_period)) or 0
    failed = db.scalar(select(func.count(PipelineRun.id)).where(in_period, PipelineRun.status == "failed")) or 0
    opened = db.scalars(
        select(Incident.title).where(Incident.project_id == project_id, Incident.opened_at >= since)
        .order_by(Incident.opened_at.desc()).limit(5)
    ).all()
    opened_count = db.scalar(
        select(func.count(Incident.id)).where(Incident.project_id == project_id, Incident.opened_at >= since)
    ) or 0
    still_open = db.scalar(
        select(func.count(Incident.id)).where(Incident.project_id == project_id, Incident.status != "resolved")
    ) or 0
    versions = db.scalar(
        select(func.count(DatasetVersion.id)).join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.project_id == project_id, DatasetVersion.created_at >= since)
    ) or 0

    lines = [
        f"{count_of(runs, 'run')} this week, {failed} of them failed." if runs else "No runs this week.",
        f"{count_of(versions, 'new dataset version')} saved.",
    ]
    if opened_count:
        lines.append(f"{count_of(opened_count, 'incident')} opened: " + "; ".join(opened) + ("; and more." if opened_count > len(opened) else "."))
    else:
        lines.append("No new incidents.")
    lines.append(f"{count_of(still_open, 'incident')} still open." if still_open else "Nothing is waiting on anyone.")
    return f"{name}: the week in brief", "\n".join(lines)


def send_weekly_summaries(db: Session, *, now: datetime | None = None) -> int:
    """Send every due weekly summary. Returns how many were attempted."""
    moment = now or datetime.now(UTC)
    attempted = 0
    targets = db.scalars(select(ExternalNotificationTarget).where(ExternalNotificationTarget.enabled.is_(True))).all()
    for target in targets:
        subscribed = target.subscribed_event_types_json
        if not isinstance(subscribed, list) or EVENT not in subscribed:
            continue
        last = _aware(target.last_summary_sent_at)
        if last is not None and moment - last < WEEK:
            continue
        attempted += 1
        # Marked before sending: a failing mail server must not make every
        # ticker pass try again; next week's attempt is the retry.
        target.last_summary_sent_at = moment
        db.commit()
        try:
            title, message = build_summary(db, target.project_id, since=last or moment - WEEK, now=moment)
            config = notification_target_config_for_internal_use(target.target_type, target.config_json or {})
            if target.target_type == EXTERNAL_TARGET_EMAIL:
                ok, detail = send_email_event_message(config=config, title=title, message=message, level="info", event_type=EVENT)
            elif target.target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
                ok, detail = send_slack_event_message(config=config, title=title, message=message, level="info", event_type=EVENT)
            else:
                continue
            if not ok:
                logger.warning("weekly_summary_not_sent target_id=%s detail=%s", target.id, detail)
        except Exception:  # noqa: BLE001 - one target's failure must not stop the others
            logger.exception("weekly_summary_failed target_id=%s", target.id)
    return attempted
