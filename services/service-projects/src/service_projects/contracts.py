from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import Uuid, bindparam, func, select, text
from sqlalchemy.orm import Session

from service_projects.models import Project
from shared_python.errors import NotFoundError


def ensure_project_exists(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    return project


# Projects gained members in Phase 03, but the ownership check lives here and is
# called from a dozen services that must not depend on the membership service --
# that would be a cycle. So the lookup is injected: `service_access` registers a
# resolver at import time, and until it does, the behaviour is exactly what it
# was before, owner-only. A missing resolver therefore fails closed rather than
# opening a project up to everyone.
RoleResolver = Callable[[Session, uuid.UUID, uuid.UUID], str | None]
SharedProjectsResolver = Callable[[Session, uuid.UUID], list[uuid.UUID]]

_role_resolver: RoleResolver | None = None
_shared_projects_resolver: SharedProjectsResolver | None = None


def register_role_resolver(resolver: RoleResolver | None) -> None:
    """Teach the ownership check about project membership."""
    global _role_resolver
    _role_resolver = resolver


def register_shared_projects_resolver(resolver: SharedProjectsResolver | None) -> None:
    """Teach the project list about projects shared with the caller."""
    global _shared_projects_resolver
    _shared_projects_resolver = resolver


def shared_project_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Projects this user can reach without owning, or an empty list."""
    if _shared_projects_resolver is None:
        return []
    return _shared_projects_resolver(db, user_id)


def project_role(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """This user's role on this project, or None when they have no access.

    When a resolver is registered it is authoritative, *including* for the
    owner. Short-circuiting on ownership would mean a project moved to another
    organisation stayed visible to whoever created it -- a leak between tenants
    that no amount of membership checking downstream could catch.

    With no resolver -- a single-tenant install -- ownership is the whole answer,
    exactly as before.
    """
    project = db.get(Project, project_id)
    if project is None:
        return None
    if _role_resolver is not None:
        return _role_resolver(db, project_id, user_id)
    if project.owner_user_id is not None and project.owner_user_id == user_id:
        return "admin"
    return None


# Returning 404 for non-accessible resources avoids leaking which project IDs exist.
def ensure_owned_project(db: Session, project_id: uuid.UUID, owner_user_id: uuid.UUID) -> Project:
    """Assert the user may *see* this project, and hand it back.

    Read access only. What a member may change is decided once, at the gateway,
    from the request itself -- see `service_access.permissions`. Putting that
    decision here instead would mean every one of the hundred-plus call sites
    had to know which of them were writes.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    if project_role(db, project_id, owner_user_id) is not None:
        return project
    raise NotFoundError("Project not found.")


def _count_by_project(table: str) -> text:
    """A row count scoped to one project.

    Raw SQL because these live in `service_projects`, which must not import the
    models of the services that own these tables. The bind parameter is typed
    explicitly: an untyped one is handed straight to the driver, which works on
    Postgres and fails anywhere else -- including the SQLite the test suite runs
    on.
    """
    return text(f"SELECT COUNT(*) FROM {table} WHERE project_id = :project_id").bindparams(
        bindparam("project_id", type_=Uuid(as_uuid=True))
    )


_COUNT_SOURCES = _count_by_project("sources")
_COUNT_DATASETS = _count_by_project("datasets")
_COUNT_RUNS = _count_by_project("pipeline_runs")


def count_project_sources(db: Session, project_id: uuid.UUID) -> int:
    return db.execute(_COUNT_SOURCES, {"project_id": project_id}).scalar_one() or 0


def count_project_datasets(db: Session, project_id: uuid.UUID) -> int:
    return db.execute(_COUNT_DATASETS, {"project_id": project_id}).scalar_one() or 0


def count_project_runs(db: Session, project_id: uuid.UUID) -> int:
    return db.execute(_COUNT_RUNS, {"project_id": project_id}).scalar_one() or 0


def total_projects(db: Session) -> int:
    return db.scalar(select(func.count(Project.id))) or 0
