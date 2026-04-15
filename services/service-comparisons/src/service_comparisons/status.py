from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_comparisons.models import SavedStatisticalTest
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    total = db.scalar(select(func.count()).select_from(SavedStatisticalTest)) or 0
    return ServiceStatus(
        name="service-comparisons",
        status="healthy",
        details={"saved_statistical_test_count": int(total)},
    )
