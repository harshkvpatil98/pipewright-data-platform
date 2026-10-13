from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_notifications.models import UserNotification
from service_notifications.preferences import category_for, mode_for
from service_notifications.schemas import (
    MarkAllNotificationsReadResponse,
    MarkNotificationReadResponse,
    UserNotificationListResponse,
    UserNotificationRead,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import NotFoundError


_DIGEST_NOUNS = {
    "failures": ("failure", "failures"),
    "incidents": ("incident", "incidents"),
    "mentions": ("mention", "mentions"),
    "reports": ("report sent", "reports sent"),
    "workflows": ("workflow message", "workflow messages"),
}


def _digest_title(category: str, count: int, period: str = "today") -> str:
    """The running count a daily or weekly summary shows as its title."""
    if category == "successes":
        return f"{count} run{'' if count == 1 else 's'} finished without problems {period}"
    one, many = _DIGEST_NOUNS.get(category, ("update", "updates"))
    return f"{count} {one if count == 1 else many} {period}"


def _summary_period(mode: str) -> tuple[str, str]:
    """The group a summary row collects into, and how its title names the period."""
    now = datetime.now(UTC)
    if mode == "weekly":
        year, week, _day = now.isocalendar()
        return f"{year}-W{week:02d}", "this week"
    return now.date().isoformat(), "today"


def create_user_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    type: str,
    level: str,
    title: str,
    message: str,
    related_run_id: uuid.UUID | None = None,
    related_schedule_id: uuid.UUID | None = None,
    related_dataset_id: uuid.UUID | None = None,
    related_pipeline_id: uuid.UUID | None = None,
) -> UserNotificationRead | None:
    """Record one event for one person, the way they asked to hear about it.

    "Off" records nothing. "Digest" folds the event into one row per
    category, project and day whose title is a running count. "Each" adds a
    row, except that a repeat of an unread warning or failure for the same
    schedule, recipe or dataset folds into the existing row and counts,
    rather than stacking the same red line twenty times. Returns the row
    written or updated, or None when the person turned this kind off.
    """
    category = category_for(type, level)
    mode = mode_for(db, user_id, category)
    if mode == "off":
        return None

    group_key: str | None = None
    summary = mode in ("digest", "weekly")
    period_key, period = _summary_period(mode)
    if summary:
        group_key = f"{mode}:{category}:{project_id or 'all'}:{period_key}"
    elif level in {"error", "warning"}:
        subject = related_schedule_id or related_pipeline_id or related_dataset_id
        if subject is not None:
            group_key = f"{type}:{subject}"

    if group_key is not None:
        query = select(UserNotification).where(
            UserNotification.user_id == user_id, UserNotification.group_key == group_key
        )
        if not summary:
            # A repeat after the person has read the first is news again.
            query = query.where(UserNotification.is_read.is_(False))
        existing = db.scalars(query.limit(1)).first()
        if existing is not None:
            existing.group_count = (existing.group_count or 1) + 1
            if summary:
                existing.title = _digest_title(category, existing.group_count, period)
                existing.message = f"Latest: {title}. {message}".strip()[:4000]
            else:
                existing.title = title[:240]
                existing.message = message
                existing.level = level
            existing.related_run_id = related_run_id or existing.related_run_id
            existing.updated_at = datetime.now(UTC)
            db.commit()
            db.refresh(existing)
            return UserNotificationRead.model_validate(existing, from_attributes=True)

    row = UserNotification(
        user_id=user_id,
        project_id=project_id,
        type=f"digest_{category}" if summary else type,
        level=level,
        title=(_digest_title(category, 1, period) if summary else title)[:240],
        message=(f"Latest: {title}. {message}".strip()[:4000] if summary else message),
        related_run_id=related_run_id,
        related_schedule_id=related_schedule_id,
        related_dataset_id=related_dataset_id,
        related_pipeline_id=related_pipeline_id,
        is_read=False,
        read_at=None,
        group_key=group_key,
        group_count=1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return UserNotificationRead.model_validate(row, from_attributes=True)


def _unread_count(db: Session, *, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(UserNotification)
            .where(and_(UserNotification.user_id == user_id, UserNotification.is_read.is_(False)))
        )
        or 0
    )


def list_notifications_for_user(
    db: Session,
    *,
    current_user: UserRead,
    project_id: uuid.UUID | None = None,
    limit: int = 100,
) -> UserNotificationListResponse:
    lim = max(1, min(limit, 200))
    stmt = (
        select(UserNotification)
        .where(UserNotification.user_id == current_user.id)
        # Most recent activity first: a grouped row moves up when it counts again.
        .order_by(UserNotification.updated_at.desc(), UserNotification.created_at.desc())
        .limit(lim)
    )
    if project_id is not None:
        ensure_owned_project(db, project_id, current_user.id)
        stmt = stmt.where(UserNotification.project_id == project_id)
    rows = db.scalars(stmt).all()
    return UserNotificationListResponse(
        items=[UserNotificationRead.model_validate(r, from_attributes=True) for r in rows],
        unread_count=_unread_count(db, user_id=current_user.id),
    )


def mark_notification_read(
    db: Session, *, notification_id: uuid.UUID, current_user: UserRead
) -> MarkNotificationReadResponse:
    row = db.get(UserNotification, notification_id)
    if row is None or row.user_id != current_user.id:
        raise NotFoundError("Notification not found.")
    now = datetime.now(UTC)
    row.is_read = True
    row.read_at = now
    db.commit()
    db.refresh(row)
    return MarkNotificationReadResponse(notification=UserNotificationRead.model_validate(row, from_attributes=True))


def mark_all_notifications_read(db: Session, *, current_user: UserRead) -> MarkAllNotificationsReadResponse:
    result = db.execute(
        update(UserNotification)
        .where(and_(UserNotification.user_id == current_user.id, UserNotification.is_read.is_(False)))
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    db.commit()
    return MarkAllNotificationsReadResponse(updated_count=result.rowcount or 0)
