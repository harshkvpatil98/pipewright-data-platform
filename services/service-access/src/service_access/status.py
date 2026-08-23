from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_access.service import shared_project_count, total_memberships


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-access",
        status="healthy",
        details={
            "memberships": total_memberships(db),
            "shared_projects": shared_project_count(db),
            "enforcement": "gateway guard on every project-scoped request",
        },
    )
