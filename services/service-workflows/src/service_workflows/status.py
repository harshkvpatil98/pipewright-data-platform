from sqlalchemy.orm import Session

from service_workflows.cron import due_workflows
from service_workflows.queue import oldest_queued_at, queue_depth, running_count
from service_workflows.service import total_workflows
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    queued = queue_depth(db)
    return ServiceStatus(
        name="service-workflows",
        status="healthy",
        details={
            "workflow_count": total_workflows(db),
            "runs_queued": queued,
            "runs_running": running_count(db),
            # ISO or None; None means the queue is empty, not "unknown".
            "oldest_queued_at": (
                oldest.isoformat() if (oldest := oldest_queued_at(db)) else None
            ),
            "schedules_due_now": len(due_workflows(db)),
        },
    )
