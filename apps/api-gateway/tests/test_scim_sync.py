"""SCIM-lite deactivate-on-absence, at the invariants that make it safe to cron.

Getting this wrong locks people out, so the guarantees are asserted directly: a
directory-managed account absent from the snapshot is deactivated (and its
sessions ended), a local account never is no matter what, and the platform is
never left without an active admin.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.scim_sync import deactivate_absent_sso_users
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base


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


def _user(db: Session, username: str, *, source: str = "sso", role: str = "viewer", active: bool = True) -> User:
    u = User(
        username=username,
        password_hash=hash_password("x"),
        role=role,
        is_active=active,
        auth_source=source,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _get(db: Session, username: str) -> User:
    return db.query(User).filter(User.username == username).one()


def test_an_absent_sso_user_is_deactivated_and_signed_out(db: Session) -> None:
    _user(db, "local-admin", source="local", role="admin")
    present = _user(db, "dana@acme.com")
    absent = _user(db, "gone@acme.com")
    before = absent.token_version

    summary = deactivate_absent_sso_users(db, present_usernames={"dana@acme.com"})

    assert summary["deactivated"] == ["gone@acme.com"]
    assert _get(db, "gone@acme.com").is_active is False
    # Sessions ended: token_version bumped so any live JWT is now invalid.
    assert _get(db, "gone@acme.com").token_version == before + 1
    assert _get(db, "dana@acme.com").is_active is True
    _ = present


def test_a_local_account_is_never_swept(db: Session) -> None:
    _user(db, "founder", source="local", role="admin")
    # An empty directory snapshot: every SSO user is absent, but local stays.
    summary = deactivate_absent_sso_users(db, present_usernames=set())
    assert "founder" not in summary["deactivated"]
    assert _get(db, "founder").is_active is True


def test_the_last_admin_is_skipped_not_locked_out(db: Session) -> None:
    # An SSO admin who is the only admin and has left the directory: skipping is
    # safer than locking everyone out of administration.
    _user(db, "sso-admin@acme.com", source="sso", role="admin")
    summary = deactivate_absent_sso_users(db, present_usernames=set())
    assert summary["deactivated"] == []
    assert summary["skipped_last_admin"] == ["sso-admin@acme.com"]
    assert _get(db, "sso-admin@acme.com").is_active is True


def test_one_of_several_admins_can_be_deactivated(db: Session) -> None:
    _user(db, "local-admin", source="local", role="admin")  # keeps an admin alive
    _user(db, "sso-admin@acme.com", source="sso", role="admin")
    summary = deactivate_absent_sso_users(db, present_usernames=set())
    # The local admin keeps administration alive, so the absent SSO admin goes.
    assert summary["deactivated"] == ["sso-admin@acme.com"]
    assert _get(db, "sso-admin@acme.com").is_active is False


def test_dry_run_changes_nothing(db: Session) -> None:
    _user(db, "gone@acme.com")
    summary = deactivate_absent_sso_users(db, present_usernames=set(), dry_run=True)
    assert summary["deactivated"] == ["gone@acme.com"]
    assert summary["dry_run"] is True
    # ...but the account is untouched.
    assert _get(db, "gone@acme.com").is_active is True


def test_already_inactive_users_are_left_alone(db: Session) -> None:
    _user(db, "already-off@acme.com", active=False)
    summary = deactivate_absent_sso_users(db, present_usernames=set())
    assert summary["deactivated"] == []
    assert summary["checked"] == 0  # only active managed accounts are considered
