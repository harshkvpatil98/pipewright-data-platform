"""Taking a user or a project back out of an organisation.

Tenancy was append-only. `assign_user` put somebody into an organisation and
nothing took them out, so an offboarded colleague kept access to every project
in that tenant for as long as their account existed -- and project-level
membership could be revoked while this could not.

The other half of these tests is about refusing to strand things. `same_tenant`
compares a project's organisation with the caller's, so "belongs to no tenant"
is not a neutral state: it is only visible to users who also belong to none.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_enterprise import tenancy
from service_enterprise.models import Organisation
from service_enterprise.service import (
    assign_project,
    assign_user,
    delete_organisation,
    unassign_project,
    unassign_user,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import ConflictError, ForbiddenError, NotFoundError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _read(user: User, role: str = "admin") -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role=role, is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    admin = User(username="admin", password_hash="x", role="admin", is_active=True)
    analyst = User(username="analyst", password_hash="x", role="viewer", is_active=True)
    db.add_all([admin, analyst])
    db.flush()
    org = Organisation(name="Acme", slug="acme", plan="standard", is_active=True)
    db.add(org)
    db.flush()
    project = Project(
        name="Revenue", slug="revenue", owner_user_id=analyst.id, status="active",
    )
    db.add(project)
    db.commit()
    return {"admin": admin, "analyst": analyst, "org": org, "project": project}


# --------------------------------------------------------------- membership


def test_a_user_can_be_removed_from_an_organisation(db: Session, world: dict):
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)
    assert db.get(User, world["analyst"].id).organisation_id == world["org"].id

    unassign_user(db, world["org"].id, world["analyst"].id, actor)

    assert db.get(User, world["analyst"].id).organisation_id is None


def test_revoking_membership_cuts_off_access_to_the_tenants_projects(
    db: Session, world: dict
):
    """What the missing endpoint actually cost.

    The project stays in the organisation; the person does not. `same_tenant`
    is what turns that into a loss of access, with no membership row touched.
    """
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)
    assign_project(db, world["org"].id, world["project"].id, actor)
    assert tenancy.same_tenant(db, world["project"].id, world["analyst"].id)

    unassign_user(db, world["org"].id, world["analyst"].id, actor)

    assert not tenancy.same_tenant(db, world["project"].id, world["analyst"].id)


def test_removing_a_user_from_an_organisation_they_are_not_in_is_a_404(
    db: Session, world: dict
):
    """Otherwise naming the wrong tenant would still remove them from theirs."""
    actor = _read(world["admin"])
    other = Organisation(name="Other", slug="other", plan="standard", is_active=True)
    db.add(other)
    db.commit()
    assign_user(db, world["org"].id, world["analyst"].id, actor)

    with pytest.raises(NotFoundError):
        unassign_user(db, other.id, world["analyst"].id, actor)

    assert db.get(User, world["analyst"].id).organisation_id == world["org"].id


def test_only_a_platform_admin_may_revoke_membership(db: Session, world: dict):
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)

    with pytest.raises(ForbiddenError):
        unassign_user(
            db, world["org"].id, world["analyst"].id, _read(world["analyst"], "viewer")
        )


# ------------------------------------------------------------------ projects


def test_a_project_can_leave_an_organisation_when_its_owner_has_none(
    db: Session, world: dict
):
    actor = _read(world["admin"])
    assign_project(db, world["org"].id, world["project"].id, actor)

    unassign_project(db, world["org"].id, world["project"].id, actor)

    assert db.get(Project, world["project"].id).organisation_id is None


def test_a_project_whose_owner_is_in_a_tenant_may_not_be_stranded(
    db: Session, world: dict
):
    """The refusal that stops a project disappearing from everyone at once.

    With the owner in an organisation and the project in none, `same_tenant`
    is false for the owner, its members and every admin -- while the datasets
    and runs stay in the database.
    """
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)
    assign_project(db, world["org"].id, world["project"].id, actor)

    with pytest.raises(ConflictError, match="unreachable"):
        unassign_project(db, world["org"].id, world["project"].id, actor)

    assert db.get(Project, world["project"].id).organisation_id == world["org"].id


def test_removing_a_project_from_the_wrong_organisation_is_a_404(
    db: Session, world: dict
):
    actor = _read(world["admin"])
    other = Organisation(name="Other", slug="other", plan="standard", is_active=True)
    db.add(other)
    db.commit()
    assign_project(db, world["org"].id, world["project"].id, actor)

    with pytest.raises(NotFoundError):
        unassign_project(db, other.id, world["project"].id, actor)


# ------------------------------------------------------------- organisations


def test_an_empty_organisation_can_be_deleted(db: Session, world: dict):
    delete_organisation(db, world["org"].id, _read(world["admin"]))
    assert db.get(Organisation, world["org"].id) is None


def test_an_organisation_holding_projects_cannot_be_deleted(db: Session, world: dict):
    """`organisation_id` has no foreign key behind it on either table.

    Nothing in the database would stop the delete, and nothing would report the
    rows left pointing at a tenant that no longer exists -- they would just
    stop matching anything.
    """
    actor = _read(world["admin"])
    assign_project(db, world["org"].id, world["project"].id, actor)

    with pytest.raises(ConflictError, match="still holds"):
        delete_organisation(db, world["org"].id, actor)

    assert db.get(Organisation, world["org"].id) is not None


def test_an_organisation_holding_members_cannot_be_deleted(db: Session, world: dict):
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)

    with pytest.raises(ConflictError, match="still holds"):
        delete_organisation(db, world["org"].id, actor)


def test_an_organisation_can_be_deleted_once_it_is_emptied(db: Session, world: dict):
    actor = _read(world["admin"])
    assign_user(db, world["org"].id, world["analyst"].id, actor)
    unassign_user(db, world["org"].id, world["analyst"].id, actor)

    delete_organisation(db, world["org"].id, actor)
    assert db.get(Organisation, world["org"].id) is None


def test_deleting_an_organisation_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_organisation(db, uuid.uuid4(), _read(world["admin"]))
