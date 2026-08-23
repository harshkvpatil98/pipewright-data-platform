"""Project membership and role-based access control.

Importing this package registers the membership lookup with
`service_projects`, which is what turns every existing ownership check into a
membership check. That side effect is deliberate and is the reason the import
exists in the gateway even where nothing references the module directly.
"""

from sqlalchemy import select

from service_projects.contracts import (
    register_role_resolver,
    register_shared_projects_resolver,
)

from service_access.guard import build_project_guard
from service_access.models import ProjectMembership
from service_access.permissions import ROLES, evaluate, required_role
from service_access.resolver import accessible_project_ids, role_for
from service_access.router import build_router
from service_access.status import get_service_status


def _shared_ids(db, user_id):
    """Only the shared ones -- the project list already covers owned projects."""
    return list(
        db.scalars(
            select(ProjectMembership.project_id).where(ProjectMembership.user_id == user_id)
        ).all()
    )


register_role_resolver(role_for)
register_shared_projects_resolver(_shared_ids)

__all__ = [
    "ROLES",
    "accessible_project_ids",
    "build_project_guard",
    "build_router",
    "evaluate",
    "get_service_status",
    "required_role",
    "role_for",
]
