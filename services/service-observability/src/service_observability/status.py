from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_observability.models import DatasetMetric, FreshnessPolicy, Incident


def get_service_status(db: Session) -> ServiceStatus:
    open_incidents = (
        db.scalar(
            select(func.count(Incident.id)).where(Incident.status.in_(("open", "acknowledged")))
        )
        or 0
    )
    critical = (
        db.scalar(
            select(func.count(Incident.id)).where(
                Incident.status.in_(("open", "acknowledged")), Incident.severity == "critical"
            )
        )
        or 0
    )
    return ServiceStatus(
        name="service-observability",
        # Open incidents are the point of the service, not a fault in it.
        status="degraded" if critical else "healthy",
        details={
            "metrics_recorded": db.scalar(select(func.count(DatasetMetric.id))) or 0,
            "freshness_policies": db.scalar(select(func.count(FreshnessPolicy.id))) or 0,
            "incidents_open": open_incidents,
            "incidents_critical": critical,
        },
    )
