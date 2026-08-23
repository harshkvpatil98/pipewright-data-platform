"""Membership over real rows, including the ways it could lock someone out."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the resolver with service_projects
from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project, project_role
from service_projects.models import Project
from service_projects.service import list_projects
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError

from service_access.models import ProjectMembership
from service_access.resolver import accessible_project_ids, role_for
from service_access.schemas import MemberInvite, MemberRoleUpdate
from service_access.service import (
    invite_member,
    list_members,
    remove_member,
    role_catalog,
    update_member_role,
)


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


def _user(db: Session, username: str) -> User:
    row = User(username=username, password_hash="x", role="admin", is_active=True)
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
    owner = _user(db, "owner")
    analyst = _user(db, "analyst")
    stranger = _user(db, "stranger")
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.commit()
    return {"owner": owner, "analyst": analyst, "stranger": stranger, "project": project}


def test_the_owner_is_an_admin_without_a_membership_row(db: Session, world: dict):
    assert role_for(db, world["project"].id, world["owner"].id) == "admin"
    assert db.query(ProjectMembership).count() == 0


def test_a_stranger_has_no_role(db: Session, world: dict):
    assert role_for(db, world["project"].id, world["stranger"].id) is None


def test_a_member_gets_the_role_they_were_given(db: Session, world: dict):
    invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="editor"), _read(world["owner"])
    )
    assert role_for(db, world["project"].id, world["analyst"].id) == "editor"


def test_a_member_can_now_reach_the_project(db: Session, world: dict):
    """The whole point: ownership checks stop being owner-only."""
    with pytest.raises(NotFoundError):
        ensure_owned_project(db, world["project"].id, world["analyst"].id)

    invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="viewer"), _read(world["owner"])
    )
    assert ensure_owned_project(db, world["project"].id, world["analyst"].id).id == world["project"].id


def test_a_shared_project_appears_in_the_members_project_list(db: Session, world: dict):
    assert list_projects(db, _read(world["analyst"])).items == []

    invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="viewer"), _read(world["owner"])
    )
    listed = list_projects(db, _read(world["analyst"])).items
    assert [item.name for item in listed] == ["Ops"]


def test_the_owner_still_sees_their_own_projects(db: Session, world: dict):
    assert [item.name for item in list_projects(db, _read(world["owner"])).items] == ["Ops"]


def test_an_owner_who_is_also_a_member_is_listed_once(db: Session, world: dict):
    db.add(
        ProjectMembership(
            project_id=world["project"].id, user_id=world["owner"].id, role="viewer"
        )
    )
    db.commit()
    assert len(list_projects(db, _read(world["owner"])).items) == 1
    assert len(accessible_project_ids(db, world["owner"].id)) == 1


def test_ownership_outranks_a_lesser_membership_row(db: Session, world: dict):
    """An owner demoted in the membership table must not lose their project."""
    db.add(
        ProjectMembership(
            project_id=world["project"].id, user_id=world["owner"].id, role="viewer"
        )
    )
    db.commit()
    assert role_for(db, world["project"].id, world["owner"].id) == "admin"


def test_inviting_someone_twice_is_refused_with_advice(db: Session, world: dict):
    invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="viewer"), _read(world["owner"])
    )
    with pytest.raises(BadRequestError) as caught:
        invite_member(
            db, world["project"].id, MemberInvite(username="analyst", role="editor"), _read(world["owner"])
        )
    assert "change their role instead" in str(caught.value.detail)


def test_inviting_the_owner_is_refused(db: Session, world: dict):
    with pytest.raises(BadRequestError) as caught:
        invite_member(
            db, world["project"].id, MemberInvite(username="owner", role="viewer"), _read(world["owner"])
        )
    assert "owns this project" in str(caught.value.detail)


def test_inviting_a_username_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        invite_member(
            db, world["project"].id, MemberInvite(username="ghost", role="viewer"), _read(world["owner"])
        )


def test_usernames_are_matched_case_insensitively(db: Session, world: dict):
    member = invite_member(
        db, world["project"].id, MemberInvite(username="ANALYST", role="viewer"), _read(world["owner"])
    )
    assert member.username == "analyst"


def test_you_cannot_change_your_own_role(db: Session, world: dict):
    """Otherwise an admin can demote themselves and orphan the project."""
    membership = invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="admin"), _read(world["owner"])
    )
    with pytest.raises(BadRequestError):
        update_member_role(
            db,
            world["project"].id,
            membership.id,
            MemberRoleUpdate(role="viewer"),
            _read(world["analyst"]),
        )


def test_you_cannot_remove_your_own_access(db: Session, world: dict):
    membership = invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="admin"), _read(world["owner"])
    )
    with pytest.raises(BadRequestError):
        remove_member(db, world["project"].id, membership.id, _read(world["analyst"]))


def test_an_admin_can_change_someone_elses_role(db: Session, world: dict):
    membership = invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="viewer"), _read(world["owner"])
    )
    updated = update_member_role(
        db, world["project"].id, membership.id, MemberRoleUpdate(role="operator"), _read(world["owner"])
    )
    assert updated.role == "operator"
    assert role_for(db, world["project"].id, world["analyst"].id) == "operator"


def test_removing_a_member_takes_their_access_away(db: Session, world: dict):
    membership = invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="editor"), _read(world["owner"])
    )
    remove_member(db, world["project"].id, membership.id, _read(world["owner"]))
    assert role_for(db, world["project"].id, world["analyst"].id) is None


def test_a_membership_from_another_project_is_not_found(db: Session, world: dict):
    membership = invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="viewer"), _read(world["owner"])
    )
    other = Project(name="Other", slug="other", owner_user_id=world["owner"].id, status="active")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundError):
        remove_member(db, other.id, membership.id, _read(world["owner"]))


def test_the_member_list_puts_the_owner_first_and_says_your_role(db: Session, world: dict):
    invite_member(
        db, world["project"].id, MemberInvite(username="analyst", role="operator"), _read(world["owner"])
    )
    listing = list_members(db, world["project"].id, _read(world["analyst"]))

    assert listing.items[0].is_owner is True
    assert listing.items[0].username == "owner"
    assert listing.items[1].username == "analyst"
    assert listing.items[1].invited_by_username == "owner"
    assert listing.your_role == "operator"


def test_project_role_returns_none_for_a_project_that_does_not_exist(db: Session, world: dict):
    assert project_role(db, uuid.uuid4(), world["owner"].id) is None


def test_the_role_catalog_explains_each_role():
    catalog = role_catalog()
    assert [item.role for item in catalog.items] == ["viewer", "operator", "editor", "admin"]
    assert all(item.description for item in catalog.items)
