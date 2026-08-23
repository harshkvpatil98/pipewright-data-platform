"""Resolving a user's role on a project.

Separated from the router so that every service -- and the gateway guard --
answers the question the same way, and so the answer can be cached for the life
of one request instead of being asked once per ownership check.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_projects.models import Project

from service_access.models import ProjectMembership
from service_access.permissions import OWNER_ROLE, normalise_role


def role_for(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """This user's role on this project, or None if they have no access.

    The owner is an implicit admin: they created the project and cannot lock
    themselves out by editing the membership table.
    """
    project = db.get(Project, project_id)
    if project is None:
        return None
    if project.owner_user_id is not None and project.owner_user_id == user_id:
        return OWNER_ROLE

    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    if membership is None:
        return None
    return normalise_role(membership.role)


def accessible_project_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Every project this user can see, owned or shared."""
    owned = db.scalars(select(Project.id).where(Project.owner_user_id == user_id)).all()
    shared = db.scalars(
        select(ProjectMembership.project_id).where(ProjectMembership.user_id == user_id)
    ).all()
    # dict.fromkeys keeps the order stable and drops the overlap when someone
    # is both owner and an explicit member.
    return list(dict.fromkeys([*owned, *shared]))
