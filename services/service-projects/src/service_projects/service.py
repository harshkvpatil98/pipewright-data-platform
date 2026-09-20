from __future__ import annotations

import re
import uuid
from unicodedata import normalize

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import (
    shared_project_ids,
    count_project_datasets,
    count_project_sources,
    ensure_owned_project,
)
from service_projects.models import Project
from service_projects.schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectListResponse,
    ProjectSummary,
    ProjectUpdate,
)


def _slugify(value: str) -> str:
    ascii_value = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "project"


def _unique_slug(db: Session, base_slug: str) -> str:
    slug = base_slug
    suffix = 2
    while db.scalar(select(Project.id).where(Project.slug == slug).limit(1)) is not None:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _serialize_summary(project: Project, source_count: int, dataset_count: int) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        owner_user_id=project.owner_user_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        status=project.status,
        environment=project.environment,
        requires_approval=project.requires_approval,
        promoted_from_project_id=project.promoted_from_project_id,
        source_count=source_count,
        dataset_count=dataset_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def list_projects(db: Session, current_user: UserRead) -> ProjectListResponse:
    # Projects someone shared with you belong in this list too, otherwise being
    # given access to a project leaves you with no way to reach it.
    shared_ids = shared_project_ids(db, current_user.id)
    condition = Project.owner_user_id == current_user.id
    if shared_ids:
        condition = or_(condition, Project.id.in_(shared_ids))

    projects = db.scalars(
        select(Project)
        .where(condition)
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
    ).all()
    return ProjectListResponse(
        items=[
            _serialize_summary(
                project,
                count_project_sources(db, project.id),
                count_project_datasets(db, project.id),
            )
            for project in projects
        ]
    )


def get_project_by_id(db: Session, project_id: uuid.UUID, current_user: UserRead) -> ProjectDetail:
    project = ensure_owned_project(db, project_id, current_user.id)
    return ProjectDetail(
        **_serialize_summary(
            project,
            count_project_sources(db, project.id),
            count_project_datasets(db, project.id),
        ).model_dump()
    )


def create_project(db: Session, payload: ProjectCreate, current_user: UserRead) -> ProjectDetail:
    base_slug = payload.slug or _slugify(payload.name)
    project = Project(
        owner_user_id=current_user.id,
        name=payload.name.strip(),
        slug=_unique_slug(db, base_slug),
        description=payload.description.strip() if payload.description else None,
        status=payload.status,
        # A project belongs to the tenant of whoever created it. Without this a
        # user in an organisation creates a project with no organisation, and
        # the tenancy boundary refuses them access to their own new project.
        organisation_id=getattr(current_user, "organisation_id", None),
    )
    db.add(project)
    db.commit()
    return get_project_by_id(db, project.id, current_user)


def update_project(
    db: Session, project_id: uuid.UUID, payload: ProjectUpdate, current_user: UserRead
) -> ProjectDetail:
    """Rename a project, describe it, or archive it.

    A project used to be write-once: created, and then permanent and unnamed
    for ever. The project card invites you to "add one" to a project with no
    description, and there was no request that could.

    `exclude_unset` is what makes the three fields independent. Reading them off
    the model directly would turn every omitted field into an explicit null, so
    a rename would silently clear the description -- and `description=None` is
    a request this endpoint has to honour, because clearing one is the only way
    back from a mistake.
    """
    project = ensure_owned_project(db, project_id, current_user.id)
    fields = payload.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] is not None:
        project.name = fields["name"].strip()
    if "description" in fields:
        description = fields["description"]
        project.description = description.strip() if description else None
    if "status" in fields and fields["status"] is not None:
        project.status = fields["status"]

    db.commit()
    return get_project_by_id(db, project_id, current_user)


def delete_project(db: Session, project_id: uuid.UUID, current_user: UserRead) -> None:
    """Delete a project and everything inside it.

    The contents go with it, and that is the database's job rather than this
    function's: all forty-four `project_id` foreign keys across the services
    already declare `ondelete="CASCADE"`, and the relationships on `Project`
    declare `passive_deletes=True` so SQLAlchemy does not try to null them out
    one table at a time on the way. Enumerating the dependents here instead
    would be a second, weaker copy of that schema, wrong the first time a
    service adds a table.

    Who may call this is settled before the request reaches here, by the guard
    in `service_access`: `DELETE` on a path whose second-to-last segment is
    `projects` needs the admin role. `ensure_owned_project` is still the check
    that this project is *visible* to the caller, and raises the same 404 a
    stranger gets for one that does not exist.
    """
    project = ensure_owned_project(db, project_id, current_user.id)
    db.delete(project)
    db.commit()
