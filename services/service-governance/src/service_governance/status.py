from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_governance.models import AuditEntry, ChangeRequest, Comment, ResourceVersion


def get_service_status(db: Session) -> ServiceStatus:
    open_changes = (
        db.scalar(select(func.count(ChangeRequest.id)).where(ChangeRequest.status == "open")) or 0
    )
    return ServiceStatus(
        name="service-governance",
        status="healthy",
        details={
            "versions_recorded": db.scalar(select(func.count(ResourceVersion.id))) or 0,
            "changes_awaiting_review": open_changes,
            "audit_entries": db.scalar(select(func.count(AuditEntry.id))) or 0,
            "comments": db.scalar(select(func.count(Comment.id))) or 0,
        },
    )
