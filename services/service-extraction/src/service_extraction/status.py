from sqlalchemy.orm import Session

from service_extraction.service import total_extraction_connections, total_extraction_jobs
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-extraction",
        status="healthy",
        details={
            "connection_count": total_extraction_connections(db),
            "job_count": total_extraction_jobs(db),
        },
    )
