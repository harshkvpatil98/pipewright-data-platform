"""Who `ensure_owned_project` lets through.

The check widened in Phase 03 from "are you the owner" to "may you see this",
so the test double models ownership rather than returning a fixed row: the
distinction between owner, member, and stranger is the entire behaviour.
"""

import uuid
from types import SimpleNamespace

import pytest

from service_projects.contracts import (
    ensure_owned_project,
    project_role,
    register_role_resolver,
)
from shared_python.errors import NotFoundError


class FakeDb:
    """A session that knows about exactly one project."""

    def __init__(self, project):
        self.project = project

    def get(self, _model, project_id):
        if self.project is None or self.project.id != project_id:
            return None
        return self.project


@pytest.fixture(autouse=True)
def no_membership_resolver():
    """Each test opts in to membership; the default is owner-only."""
    register_role_resolver(None)
    yield
    register_role_resolver(None)


def _project(owner_id):
    return SimpleNamespace(id=uuid.uuid4(), owner_user_id=owner_id)


def test_the_owner_gets_their_project():
    owner_id = uuid.uuid4()
    project = _project(owner_id)
    assert ensure_owned_project(FakeDb(project), project.id, owner_id) is project


def test_a_project_that_does_not_exist_is_not_found():
    with pytest.raises(NotFoundError):
        ensure_owned_project(FakeDb(None), uuid.uuid4(), uuid.uuid4())


def test_someone_elses_project_is_reported_as_not_found():
    """404 rather than 403, so the response cannot confirm the id exists."""
    project = _project(uuid.uuid4())
    with pytest.raises(NotFoundError):
        ensure_owned_project(FakeDb(project), project.id, uuid.uuid4())


def test_without_a_resolver_membership_cannot_grant_access():
    """The fallback fails closed: no resolver means owner-only, as before."""
    project = _project(uuid.uuid4())
    assert project_role(FakeDb(project), project.id, uuid.uuid4()) is None


def test_a_registered_resolver_lets_a_member_through():
    project = _project(uuid.uuid4())
    member_id = uuid.uuid4()
    register_role_resolver(lambda _db, _project_id, user_id: "viewer" if user_id == member_id else None)

    assert ensure_owned_project(FakeDb(project), project.id, member_id) is project
    with pytest.raises(NotFoundError):
        ensure_owned_project(FakeDb(project), project.id, uuid.uuid4())


def test_a_registered_resolver_is_authoritative_even_for_the_owner():
    """Ownership must not short-circuit the resolver.

    The resolver is where tenancy lives. If ownership answered first, a project
    moved to another organisation would stay visible to whoever created it --
    a leak between tenants that nothing downstream could catch. Within a
    tenant the resolver still returns 'admin' for an owner, so the composed
    behaviour is unchanged for everyone it should be unchanged for.
    """
    owner_id = uuid.uuid4()
    project = _project(owner_id)
    register_role_resolver(lambda *_: None)

    assert project_role(FakeDb(project), project.id, owner_id) is None
    with pytest.raises(NotFoundError):
        ensure_owned_project(FakeDb(project), project.id, owner_id)
