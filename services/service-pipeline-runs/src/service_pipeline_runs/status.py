from sqlalchemy.orm import Session

from service_pipeline_runs.contracts import total_pipeline_runs
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-pipeline-runs",
        status="healthy",
        details={"pipeline_run_count": total_pipeline_runs(db)},
    )
