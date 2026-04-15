from sqlalchemy.orm import Session

from service_sources.contracts import total_sources
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-sources",
        status="healthy",
        details={"source_count": total_sources(db)},
    )
