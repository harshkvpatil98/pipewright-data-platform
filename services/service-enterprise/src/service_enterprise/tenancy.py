"""The boundary nothing crosses.

Multi-tenancy is not a feature you add to the edges; it is a rule about every
query in the system. So it is enforced in exactly the place project access is
already decided -- `service_access.role_for` -- rather than as a filter each
service remembers to apply. A filter somebody forgets is a data leak between
customers, which is the one bug an organisation never recovers from.

The rule: **a project in another organisation has no role, for anybody.** Not a
403, no role at all, so it reads as "not found" everywhere, exactly like a
project you were simply never added to.

Single-tenant deployments are unaffected. A user with no organisation and a
project with no organisation are both "unassigned", and unassigned matches
unassigned. That means an existing installation keeps working with no migration
of its data, which is the only way this could be added to something already
running.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def organisation_of_project(db: Session, project_id: uuid.UUID) -> uuid.UUID | None:
    from service_projects.models import Project

    project = db.get(Project, project_id)
    return getattr(project, "organisation_id", None) if project else None


def organisation_of_user(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    from service_auth.models import User

    user = db.get(User, user_id)
    return getattr(user, "organisation_id", None) if user else None


def same_tenant(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether this person and this project are in the same organisation."""
    return organisation_of_project(db, project_id) == organisation_of_user(db, user_id)


def register() -> None:
    """Make every access check tenant-aware.

    Wrapping the existing resolver rather than replacing it: membership still
    decides what someone may do, and this only decides whether the question is
    asked at all.
    """
    from service_access.resolver import role_for as membership_role
    from service_projects.contracts import register_role_resolver

    def tenant_aware_role(
        db: Session, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> str | None:
        if not same_tenant(db, project_id, user_id):
            return None
        return membership_role(db, project_id, user_id)

    register_role_resolver(tenant_aware_role)


def visible_project_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Projects this user's organisation can see at all."""
    from service_projects.models import Project

    organisation = organisation_of_user(db, user_id)
    rows = db.scalars(
        select(Project.id).where(Project.organisation_id == organisation)
    ).all()
    return list(rows)


def check_limits(db: Session, organisation_id: uuid.UUID | None) -> dict[str, Any]:
    """Where an organisation sits against its plan's limits.

    Reported rather than enforced at this layer: telling somebody they are at
    95% of their dataset allowance is useful, and refusing their next upload
    without warning is not.
    """
    from sqlalchemy import func

    from service_datasets.models import Dataset
    from service_projects.models import Project

    from service_enterprise.models import Organisation

    if organisation_id is None:
        return {"limited": False, "reason": "This deployment is not using organisations."}

    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        return {"limited": False, "reason": "Unknown organisation."}

    project_ids = list(
        db.scalars(select(Project.id).where(Project.organisation_id == organisation_id)).all()
    )
    dataset_count = (
        db.scalar(
            select(func.count(Dataset.id)).where(Dataset.project_id.in_(project_ids or [uuid.uuid4()]))
        )
        or 0
    )

    return {
        "limited": True,
        "organisation": organisation.name,
        "plan": organisation.plan,
        "projects": {"used": len(project_ids), "limit": organisation.max_projects},
        "datasets": {"used": int(dataset_count), "limit": organisation.max_datasets},
        "warnings": _limit_warnings(
            [
                ("projects", len(project_ids), organisation.max_projects),
                ("datasets", int(dataset_count), organisation.max_datasets),
            ]
        ),
    }


def _limit_warnings(entries: list[tuple[str, int, int | None]]) -> list[str]:
    warnings: list[str] = []
    for label, used, limit in entries:
        if not limit:
            continue
        if used >= limit:
            warnings.append(f"{label.capitalize()} are at the plan limit of {limit}.")
        elif used / limit >= 0.9:
            warnings.append(f"{label.capitalize()} are at {used}/{limit} of the plan limit.")
    return warnings
