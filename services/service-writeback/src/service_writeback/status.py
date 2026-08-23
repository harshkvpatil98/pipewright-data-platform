from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_writeback.models import ChangeSet


def get_service_status(db: Session) -> ServiceStatus:
    counts = dict(
        db.execute(
            select(ChangeSet.status, func.count(ChangeSet.id)).group_by(ChangeSet.status)
        ).all()
    )
    return ServiceStatus(
        name="service-writeback",
        status="healthy",
        details={
            "change_set_count": int(sum(counts.values())),
            "draft_count": int(counts.get("draft", 0)),
            "committed_count": int(counts.get("committed", 0)),
            "rows_written": int(
                db.scalar(select(func.coalesce(func.sum(ChangeSet.rows_affected), 0))) or 0
            ),
        },
    )
