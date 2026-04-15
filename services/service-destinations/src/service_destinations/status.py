from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_destinations.models import DestinationConfig
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    total = db.scalar(select(func.count()).select_from(DestinationConfig)) or 0
    return ServiceStatus(
        name="service-destinations",
        status="healthy",
        details={"destination_count": int(total)},
    )
