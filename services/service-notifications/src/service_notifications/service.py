from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_notifications.models import UserNotification
from service_notifications.schemas import (
    MarkAllNotificationsReadResponse,
    MarkNotificationReadResponse,
    UserNotificationListResponse,
    UserNotificationRead,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import NotFoundError


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
) -> UserNotificationRead:
    row = UserNotification(
        user_id=user_id,
        project_id=project_id,
        type=type,
        level=level,
        title=title[:240],
        message=message,
        related_run_id=related_run_id,
        related_schedule_id=related_schedule_id,
        related_dataset_id=related_dataset_id,
        related_pipeline_id=related_pipeline_id,
        is_read=False,
        read_at=None,
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
        .order_by(UserNotification.created_at.desc())
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
