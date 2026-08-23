"""The tenant boundary.

This is the one test file where a failure means one customer can see another
customer's data, so it tests the boundary from both directions and checks that
a single-tenant installation is unaffected.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers membership resolution
import service_enterprise  # noqa: F401  - registers the tenancy boundary
from service_access.models import ProjectMembership
from service_auth.models import User
from service_auth.schemas import UserRead
from service_enterprise.models import Organisation
from service_enterprise.tenancy import check_limits, same_tenant, visible_project_ids
from service_projects.contracts import ensure_owned_project, project_role
from service_projects.models import Project
from service_projects.service import list_projects
from shared_python.db import Base
from shared_python.errors import NotFoundError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db: Session, username: str, organisation_id: uuid.UUID | None = None) -> User:
    row = User(
        username=username,
        password_hash="x",
        role="admin",
        is_active=True,
        organisation_id=organisation_id,
    )
    db.add(row)
    db.flush()
    return row


def _read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    acme = Organisation(name="Acme", slug="acme", plan="standard", max_projects=2)
    globex = Organisation(name="Globex", slug="globex", plan="standard")
    db.add_all([acme, globex])
    db.flush()

    acme_owner = _user(db, "acme-owner", acme.id)
    acme_analyst = _user(db, "acme-analyst", acme.id)
    globex_owner = _user(db, "globex-owner", globex.id)

    acme_project = Project(
        name="Acme ops", slug="acme-ops", owner_user_id=acme_owner.id,
        status="active", organisation_id=acme.id,
    )
    globex_project = Project(
        name="Globex ops", slug="globex-ops", owner_user_id=globex_owner.id,
        status="active", organisation_id=globex.id,
    )
    db.add_all([acme_project, globex_project])
    db.commit()

    return {
        "acme": acme, "globex": globex,
        "acme_owner": acme_owner, "acme_analyst": acme_analyst, "globex_owner": globex_owner,
        "acme_project": acme_project, "globex_project": globex_project,
    }


def test_a_person_can_reach_their_own_organisations_project(db: Session, world: dict):
    assert (
        ensure_owned_project(db, world["acme_project"].id, world["acme_owner"].id).id
        == world["acme_project"].id
    )


def test_another_organisations_project_does_not_exist_as_far_as_they_know(
    db: Session, world: dict
):
    with pytest.raises(NotFoundError):
        ensure_owned_project(db, world["globex_project"].id, world["acme_owner"].id)


def test_a_membership_across_organisations_grants_nothing(db: Session, world: dict):
    """The boundary has to beat membership, or one row of data leaks a tenant."""
    db.add(
        ProjectMembership(
            project_id=world["globex_project"].id,
            user_id=world["acme_analyst"].id,
            role="admin",
        )
    )
    db.commit()

    assert project_role(db, world["globex_project"].id, world["acme_analyst"].id) is None
    with pytest.raises(NotFoundError):
        ensure_owned_project(db, world["globex_project"].id, world["acme_analyst"].id)


def test_even_ownership_across_organisations_grants_nothing(db: Session, world: dict):
    """A project moved to another tenant stops being visible to its old owner."""
    world["acme_project"].organisation_id = world["globex"].id
    db.commit()

    with pytest.raises(NotFoundError):
        ensure_owned_project(db, world["acme_project"].id, world["acme_owner"].id)


def test_the_project_list_only_shows_your_own_tenant(db: Session, world: dict):
    listed = list_projects(db, _read(world["acme_owner"])).items
    assert [item.name for item in listed] == ["Acme ops"]


def test_a_member_within_the_tenant_still_gets_their_role(db: Session, world: dict):
    db.add(
        ProjectMembership(
            project_id=world["acme_project"].id,
            user_id=world["acme_analyst"].id,
            role="editor",
        )
    )
    db.commit()
    assert project_role(db, world["acme_project"].id, world["acme_analyst"].id) == "editor"


def test_a_single_tenant_installation_is_unaffected(db: Session):
    """Unassigned matches unassigned, so an existing deployment keeps working."""
    owner = _user(db, "solo")
    project = Project(name="Solo", slug="solo", owner_user_id=owner.id, status="active")
    db.add(project)
    db.commit()

    assert same_tenant(db, project.id, owner.id) is True
    assert ensure_owned_project(db, project.id, owner.id).id == project.id


def test_an_unassigned_user_cannot_reach_an_assigned_project(db: Session, world: dict):
    stranger = _user(db, "nobody")
    db.commit()
    with pytest.raises(NotFoundError):
        ensure_owned_project(db, world["acme_project"].id, stranger.id)


def test_visible_projects_are_scoped_to_the_tenant(db: Session, world: dict):
    visible = visible_project_ids(db, world["acme_owner"].id)
    assert visible == [world["acme_project"].id]


def test_limits_report_usage_against_the_plan(db: Session, world: dict):
    report = check_limits(db, world["acme"].id)
    assert report["limited"] is True
    assert report["projects"] == {"used": 1, "limit": 2}


def test_limits_warn_before_the_ceiling_rather_than_at_it(db: Session, world: dict):
    db.add(
        Project(
            name="Acme two", slug="acme-two", owner_user_id=world["acme_owner"].id,
            status="active", organisation_id=world["acme"].id,
        )
    )
    db.commit()
    report = check_limits(db, world["acme"].id)
    assert any("plan limit" in warning for warning in report["warnings"])


def test_a_deployment_with_no_organisations_reports_that_plainly(db: Session):
    assert check_limits(db, None)["limited"] is False


def test_a_project_is_created_inside_its_creators_tenant(db: Session, world: dict):
    """Otherwise the boundary refuses somebody access to their own new project."""
    from service_projects.schemas import ProjectCreate
    from service_projects.service import create_project

    actor = _read(world["acme_analyst"])
    actor = actor.model_copy(update={"organisation_id": world["acme"].id})

    created = create_project(db, ProjectCreate(name="New Acme thing"), actor)

    project = db.get(Project, created.id)
    assert project.organisation_id == world["acme"].id
    # And the creator can immediately reach it.
    assert ensure_owned_project(db, created.id, world["acme_analyst"].id).id == created.id


def test_a_project_created_without_a_tenant_stays_untenanted(db: Session):
    from service_projects.schemas import ProjectCreate
    from service_projects.service import create_project

    solo = _user(db, "solo-creator")
    db.commit()

    created = create_project(db, ProjectCreate(name="Solo thing"), _read(solo))
    assert db.get(Project, created.id).organisation_id is None
    assert ensure_owned_project(db, created.id, solo.id).id == created.id
