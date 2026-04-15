from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_auth.service import get_user_by_id
from service_projects.models import Project
from service_schedules.models import ScheduledOperation
from shared_python.errors import BadRequestError


def resolve_actor_user_for_schedule(db: Session, row: ScheduledOperation) -> UserRead:
    """Resolve the user that should be recorded as the actor for automated schedule runs."""
    if row.created_by_user_id is not None:
        user = get_user_by_id(db, row.created_by_user_id)
        if user is not None and bool(getattr(user, "is_active", True)):
            return UserRead.model_validate(user)
    project = db.get(Project, row.project_id)
    if project is not None and project.owner_user_id is not None:
        user = get_user_by_id(db, project.owner_user_id)
        if user is not None:
            return UserRead.model_validate(user)
    raise BadRequestError("Cannot resolve an active user to run this schedule (creator and project owner unavailable).")
