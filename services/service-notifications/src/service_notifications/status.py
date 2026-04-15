from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_notifications.models import ExternalNotificationTarget, UserNotification
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    total = db.scalar(select(func.count()).select_from(UserNotification)) or 0
    ext = db.scalar(select(func.count()).select_from(ExternalNotificationTarget)) or 0
    return ServiceStatus(
        name="service-notifications",
        status="healthy",
        details={
            "notification_row_count": int(total),
            "external_notification_target_count": int(ext),
        },
    )
