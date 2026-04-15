from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from shared_python.status import ServiceStatus


def get_service_status(db: Session) -> ServiceStatus:
    user_count = db.scalar(select(func.count(User.id))) or 0
    return ServiceStatus(name="service-auth", status="healthy", details={"user_count": user_count})
