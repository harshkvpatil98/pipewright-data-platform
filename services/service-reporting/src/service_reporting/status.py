from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_reporting.models import Dashboard, SavedChart, ScheduledReport
from service_reporting.service import due_reports


def get_service_status(db: Session) -> ServiceStatus:
    return ServiceStatus(
        name="service-reporting",
        status="healthy",
        details={
            "charts": db.scalar(select(func.count(SavedChart.id))) or 0,
            "dashboards": db.scalar(select(func.count(Dashboard.id))) or 0,
            "scheduled_reports": db.scalar(select(func.count(ScheduledReport.id))) or 0,
            "reports_due_now": len(due_reports(db)),
            "shared_dashboards": db.scalar(
                select(func.count(Dashboard.id)).where(Dashboard.share_token.is_not(None))
            )
            or 0,
        },
    )
