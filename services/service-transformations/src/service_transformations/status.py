from sqlalchemy.orm import Session

from service_transformations.contracts import SUPPORTED_TRANSFORMATION_STEP_TYPES, total_transformation_pipelines
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name='service-transformations',
        status='healthy',
        details={
            'pipeline_count': total_transformation_pipelines(db),
            'supported_step_types': SUPPORTED_TRANSFORMATION_STEP_TYPES,
        },
    )
