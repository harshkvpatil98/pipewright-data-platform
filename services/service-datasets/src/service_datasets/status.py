from sqlalchemy.orm import Session

from service_datasets.contracts import total_datasets
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-datasets",
        status="healthy",
        details={"dataset_count": total_datasets(db)},
    )
