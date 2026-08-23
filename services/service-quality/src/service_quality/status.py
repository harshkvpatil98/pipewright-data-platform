from sqlalchemy.orm import Session

from service_quality.drift_service import breaking_drift_count, unacknowledged_drift_count
from service_quality.service import failing_rule_count, total_quality_rules
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-quality",
        status="healthy",
        details={
            "rule_count": total_quality_rules(db),
            "rules_currently_failing": failing_rule_count(db),
            "unacknowledged_drift_events": unacknowledged_drift_count(db),
            "breaking_drift_events": breaking_drift_count(db),
        },
    )
