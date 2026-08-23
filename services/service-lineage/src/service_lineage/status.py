from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_datasets.models import Dataset
from service_transformations.models import TransformationPipeline
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    """Lineage stores nothing, so its health is the health of what it reads."""
    derived = db.scalar(select(func.count(Dataset.id)).where(Dataset.is_derived.is_(True))) or 0
    pipelines = db.scalar(select(func.count(TransformationPipeline.id))) or 0
    return ServiceStatus(
        name="service-lineage",
        status="healthy",
        details={
            "derived_datasets": derived,
            "pipelines_traceable": pipelines,
            "storage": "derived on read",
        },
    )
