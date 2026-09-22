"""Password change, one-time codes, invites, and API tokens.

These are the account operations a company's first security review checks. The
security-critical properties are asserted directly: a password change ends
existing sessions, a one-time code works once, an inactive invite cannot be
signed into until activated, and a token's scope caps what it may do.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth import codes, tokens
from service_auth.models import ApiToken, AuthCode, User
from service_auth.schemas import InviteRequest
from service_auth.service import (
    authenticate_user,
    change_password,
    invite_user,
    set_password_with_code,
    sign_out_everywhere,
)
from shared_python.auth.security import hash_password, verify_password
from shared_python.errors import (
    BadRequestError,
    UnauthorizedError,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk(conn, _rec):  # noqa: ANN001
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    from shared_python.db import Base

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db: Session, username: str = "alice", active: bool = True) -> User:
    u = User(
        username=username,
        password_hash=hash_password("correct horse battery"),
        role="viewer",
        is_active=active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u



# --------------------------------------------------------------- password

def test_password_change_ends_existing_sessions(db: Session) -> None:
    u = _user(db)
    before = u.token_version
    change_password(db, user_id=u.id, current="correct horse battery", new="a-brand-new-secret")
    db.refresh(u)
    # The version bump is what makes every already-issued JWT stop validating.
    assert u.token_version == before + 1
    assert verify_password("a-brand-new-secret", u.password_hash)


def test_password_change_requires_the_current_password(db: Session) -> None:
    u = _user(db)
    with pytest.raises(BadRequestError, match="current password is incorrect"):
        change_password(db, user_id=u.id, current="wrong", new="a-brand-new-secret")


def test_a_new_password_must_differ_and_be_long_enough(db: Session) -> None:
    u = _user(db)
    with pytest.raises(BadRequestError, match="different"):
        change_password(db, user_id=u.id, current="correct horse battery", new="correct horse battery")
    with pytest.raises(BadRequestError, match="at least 8"):
        change_password(db, user_id=u.id, current="correct horse battery", new="short")


def test_sign_out_everywhere_bumps_the_version(db: Session) -> None:
    u = _user(db)
    before = u.token_version
    sign_out_everywhere(db, user_id=u.id)
    db.refresh(u)
    assert u.token_version == before + 1


# --------------------------------------------------------------- one-time codes

def test_a_reset_code_works_exactly_once(db: Session) -> None:
    u = _user(db)
    code = codes.issue_code(db, user_id=u.id, purpose=codes.RESET)
    user = set_password_with_code(db, code=code, new="fresh-password-1")
    assert user.id == u.id
    # Spent: the same code cannot be replayed.
    with pytest.raises(BadRequestError, match="invalid, expired, or already used"):
        set_password_with_code(db, code=code, new="fresh-password-2")


def test_issuing_a_new_code_invalidates_the_previous_one(db: Session) -> None:
    u = _user(db)
    first = codes.issue_code(db, user_id=u.id, purpose=codes.RESET)
    codes.issue_code(db, user_id=u.id, purpose=codes.RESET)
    with pytest.raises(BadRequestError):
        set_password_with_code(db, code=first, new="fresh-password-1")


def test_an_expired_code_is_refused(db: Session) -> None:
    u = _user(db)
    code = codes.issue_code(db, user_id=u.id, purpose=codes.RESET, ttl_minutes=30)
    # Age it past its TTL.
    record = db.query(AuthCode).one()
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    with pytest.raises(BadRequestError):
        set_password_with_code(db, code=code, new="fresh-password-1")


def test_an_unknown_code_is_refused(db: Session) -> None:
    _user(db)
    with pytest.raises(BadRequestError):
        set_password_with_code(db, code="not-a-real-code-value", new="fresh-password-1")


# --------------------------------------------------------------- invites

def test_an_invited_account_is_inactive_until_activated(db: Session) -> None:
    user, code = invite_user(
        db, InviteRequest(username="newbie", role="viewer", email="n@x.co")
    )
    assert user.is_active is False
    # An inactive account cannot authenticate even with a guessed password.
    with pytest.raises(UnauthorizedError):
        authenticate_user(db, "newbie", "anything")

    activated = set_password_with_code(db, code=code, new="their-first-password")
    assert activated.is_active is True
    # Now the chosen password works.
    assert authenticate_user(db, "newbie", "their-first-password").id == user.id


def test_invite_refuses_a_duplicate_username(db: Session) -> None:
    _user(db, "taken")
    from shared_python.errors import ConflictError

    with pytest.raises(ConflictError):
        invite_user(db, InviteRequest(username="taken", role="viewer"))


# --------------------------------------------------------------- API tokens

def test_a_token_is_shown_once_and_stored_as_a_hash(db: Session) -> None:
    u = _user(db)
    record, secret = tokens.create_api_token(db, user_id=u.id, name="ci", scope="read")
    assert secret.startswith("pw_")
    # The plaintext is nowhere in the row.
    assert record.token_hash != secret
    assert secret not in record.token_hash


def test_a_token_authenticates_as_its_owner(db: Session) -> None:
    u = _user(db)
    _, secret = tokens.create_api_token(db, user_id=u.id, name="ci", scope="read")
    user, scope = tokens.authenticate_api_token(db, secret)
    assert user.id == u.id
    assert scope == "read"
    # last_used_at is stamped so a stale token is visible in the list.
    assert db.query(ApiToken).one().last_used_at is not None


def test_a_read_scoped_token_cannot_mutate(db: Session) -> None:
    assert tokens.scope_allows("read", "GET") is True
    assert tokens.scope_allows("read", "POST") is False
    assert tokens.scope_allows("read", "DELETE") is False
    assert tokens.scope_allows("write", "POST") is True
    assert tokens.scope_allows("admin", "DELETE") is True


def test_a_revoked_token_stops_working(db: Session) -> None:
    u = _user(db)
    record, secret = tokens.create_api_token(db, user_id=u.id, name="ci", scope="write")
    tokens.revoke_api_token(db, user_id=u.id, token_id=record.id)
    with pytest.raises(UnauthorizedError):
        tokens.authenticate_api_token(db, secret)


def test_a_token_for_a_deactivated_user_is_refused(db: Session) -> None:
    u = _user(db, active=True)
    _, secret = tokens.create_api_token(db, user_id=u.id, name="ci", scope="admin")
    u.is_active = False
    db.commit()
    with pytest.raises(UnauthorizedError):
        tokens.authenticate_api_token(db, secret)


def test_scope_must_be_known(db: Session) -> None:
    u = _user(db)
    with pytest.raises(BadRequestError):
        tokens.create_api_token(db, user_id=u.id, name="ci", scope="superuser")
