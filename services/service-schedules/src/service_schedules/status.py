from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_schedules.models import ScheduledOperation
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    total = db.scalar(select(func.count()).select_from(ScheduledOperation)) or 0
    return ServiceStatus(
        name="service-schedules",
        status="healthy",
        details={"scheduled_operation_count": int(total)},
    )
