"""How long a session lasts, and who gets to decide.

The resolver is process-global -- it is registered once at import time, exactly
like the project-role resolver -- so every test here restores whatever was
registered before it ran. Without that, importing `service_enterprise` anywhere
in the suite would silently change what these tests measure.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from service_auth import contracts
from service_auth.contracts import (
    MAX_SESSION_MINUTES,
    MIN_SESSION_MINUTES,
    clamp_session_minutes,
    register_session_policy_resolver,
    session_minutes_for,
)

USER_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def restore_resolver() -> Iterator[None]:
    previous = contracts._session_policy_resolver
    try:
        yield
    finally:
        register_session_policy_resolver(previous)


def test_with_no_resolver_the_deployment_default_stands() -> None:
    """A single-tenant install behaves exactly as it did before this existed."""
    register_session_policy_resolver(None)
    assert session_minutes_for(None, USER_ID, default=60) == 60


def test_a_resolver_with_no_opinion_leaves_the_default_alone() -> None:
    register_session_policy_resolver(lambda _db, _user: None)
    assert session_minutes_for(None, USER_ID, default=60) == 60


def test_an_organisation_policy_shortens_the_session() -> None:
    register_session_policy_resolver(lambda _db, _user: 15)
    assert session_minutes_for(None, USER_ID, default=60) == 15


def test_an_organisation_policy_can_also_lengthen_it() -> None:
    register_session_policy_resolver(lambda _db, _user: 480)
    assert session_minutes_for(None, USER_ID, default=60) == 480


def test_the_resolver_sees_the_user_it_is_deciding_for() -> None:
    seen: list[uuid.UUID] = []

    def resolver(_db, user_id):
        seen.append(user_id)
        return 30

    register_session_policy_resolver(resolver)
    session_minutes_for(None, USER_ID, default=60)
    assert seen == [USER_ID]


def test_an_absurd_policy_is_clamped_rather_than_obeyed() -> None:
    register_session_policy_resolver(lambda _db, _user: 0)
    assert session_minutes_for(None, USER_ID, default=60) == MIN_SESSION_MINUTES

    register_session_policy_resolver(lambda _db, _user: 10_000_000)
    assert session_minutes_for(None, USER_ID, default=60) == MAX_SESSION_MINUTES


def test_a_negative_policy_cannot_produce_an_already_expired_session() -> None:
    register_session_policy_resolver(lambda _db, _user: -5)
    assert session_minutes_for(None, USER_ID, default=60) == MIN_SESSION_MINUTES


def test_an_absurd_deployment_default_is_clamped_too() -> None:
    register_session_policy_resolver(None)
    assert session_minutes_for(None, USER_ID, default=0) == MIN_SESSION_MINUTES


def test_a_broken_resolver_cannot_stop_anybody_signing_in() -> None:
    """A misconfigured tenancy lookup must degrade to the deployment default,
    not to a failed login for everyone in the deployment."""

    def explode(_db, _user):
        raise RuntimeError("the organisations table is not there")

    register_session_policy_resolver(explode)
    assert session_minutes_for(None, USER_ID, default=60) == 60


def test_clamp_is_exposed_so_the_api_can_reject_the_same_range() -> None:
    assert clamp_session_minutes(1) == MIN_SESSION_MINUTES
    assert clamp_session_minutes(60) == 60
    assert clamp_session_minutes(MAX_SESSION_MINUTES + 1) == MAX_SESSION_MINUTES
