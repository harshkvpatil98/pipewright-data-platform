from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_datasets.models import Dataset
from shared_python.status import ServiceStatus

from service_intelligence.pii import DETECTORS
from service_intelligence.phrasing import AGGREGATION_WORDS, COMPARISON_WORDS


def get_service_status(db: Session) -> ServiceStatus:
    """Nothing is stored here; the detail says what it can recognise."""
    return ServiceStatus(
        name="service-intelligence",
        status="healthy",
        details={
            "pii_detectors": len(DETECTORS),
            "phrases_understood": len(AGGREGATION_WORDS) + len(COMPARISON_WORDS),
            "datasets_analysable": db.scalar(select(func.count(Dataset.id))) or 0,
            "method": "deterministic analysis; no model calls",
        },
    )
