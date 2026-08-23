from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_enterprise.models import (
    ErasureRequest,
    Organisation,
    RetentionPolicy,
    SecurityPolicy,
)


def get_service_status(db: Session) -> ServiceStatus:
    dry_run_only = (
        db.scalar(
            select(func.count(RetentionPolicy.id)).where(
                RetentionPolicy.enabled.is_(True), RetentionPolicy.dry_run.is_(True)
            )
        )
        or 0
    )
    return ServiceStatus(
        name="service-enterprise",
        status="healthy",
        details={
            "organisations": db.scalar(select(func.count(Organisation.id))) or 0,
            "security_policies": db.scalar(
                select(func.count(SecurityPolicy.id)).where(SecurityPolicy.enabled.is_(True))
            )
            or 0,
            "retention_policies": db.scalar(select(func.count(RetentionPolicy.id))) or 0,
            "retention_in_report_only_mode": dry_run_only,
            "erasure_requests": db.scalar(select(func.count(ErasureRequest.id))) or 0,
        },
    )
