from sqlalchemy.orm import Session

from service_projects.contracts import total_projects
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-projects",
        status="healthy",
        details={"project_count": total_projects(db)},
    )
