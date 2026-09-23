"""Second-factor authentication, asserted at the properties a review checks.

TOTP itself is verified against the RFC vectors in test_totp.py; this covers the
account flow around it: enrolment is confirmed before it gates login, a live
code and a recovery code each satisfy the second factor, a recovery code works
exactly once, the between-steps ticket cannot be forged, and an admin can clear
a locked-out account.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth import mfa, totp
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.errors import BadRequestError, UnauthorizedError

SETTINGS = SimpleNamespace(
    auth_jwt_secret="test-secret-key-for-mfa-tickets-0123456789abcdef",
    auth_jwt_issuer="test-issuer",
    auth_jwt_audience="test-audience",
)
NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
TS = int(NOW.timestamp())


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


def _user(db: Session) -> User:
    u = User(username="alice", password_hash=hash_password("correct horse"), role="viewer")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _enrol_and_activate(db: Session, user: User) -> tuple[str, list[str]]:
    challenge = mfa.begin_enrollment(db, user=user, issuer="Pipewright")
    code = totp.code_at(challenge.secret, timestamp=TS)
    recovery = mfa.activate(db, user_id=user.id, code=code, now=NOW)
    return challenge.secret, recovery


def test_enrolment_is_not_active_until_confirmed(db: Session) -> None:
    user = _user(db)
    mfa.begin_enrollment(db, user=user, issuer="Pipewright")
    # A generated-but-unconfirmed secret must not gate login, or a person who
    # started enrolment and closed the tab is locked out.
    assert mfa.is_active(db, user.id) is False
    assert mfa.status(db, user.id) == {"enrolled": True, "active": False}


def test_activating_with_a_live_code_turns_it_on_and_returns_recovery_codes(db: Session) -> None:
    user = _user(db)
    _secret, recovery = _enrol_and_activate(db, user)
    assert mfa.is_active(db, user.id) is True
    assert len(recovery) == mfa.RECOVERY_CODE_COUNT
    assert mfa.remaining_recovery_codes(db, user.id) == mfa.RECOVERY_CODE_COUNT


def test_activating_with_a_wrong_code_is_refused(db: Session) -> None:
    user = _user(db)
    mfa.begin_enrollment(db, user=user, issuer="Pipewright")
    with pytest.raises(BadRequestError):
        mfa.activate(db, user_id=user.id, code="000000", now=NOW)
    assert mfa.is_active(db, user.id) is False


def test_a_live_totp_code_satisfies_the_second_factor(db: Session) -> None:
    user = _user(db)
    secret, _ = _enrol_and_activate(db, user)
    code = totp.code_at(secret, timestamp=TS)
    assert mfa.verify_second_factor(db, user_id=user.id, code=code, now=NOW) is True
    assert mfa.verify_second_factor(db, user_id=user.id, code="000000", now=NOW) is False


def test_a_recovery_code_works_exactly_once(db: Session) -> None:
    user = _user(db)
    _secret, recovery = _enrol_and_activate(db, user)
    one = recovery[0]
    assert mfa.verify_second_factor(db, user_id=user.id, code=one, now=NOW) is True
    # Spent: the same code cannot be used again.
    assert mfa.verify_second_factor(db, user_id=user.id, code=one, now=NOW) is False
    assert mfa.remaining_recovery_codes(db, user.id) == mfa.RECOVERY_CODE_COUNT - 1


def test_regenerating_recovery_codes_invalidates_the_old_set(db: Session) -> None:
    user = _user(db)
    _secret, old = _enrol_and_activate(db, user)
    fresh = mfa.regenerate_recovery_codes(db, user_id=user.id)
    assert set(fresh).isdisjoint(old)
    assert mfa.verify_second_factor(db, user_id=user.id, code=old[0], now=NOW) is False
    assert mfa.verify_second_factor(db, user_id=user.id, code=fresh[0], now=NOW) is True


def test_re_enrolling_while_active_is_refused(db: Session) -> None:
    user = _user(db)
    _enrol_and_activate(db, user)
    with pytest.raises(BadRequestError):
        mfa.begin_enrollment(db, user=user, issuer="Pipewright")


def test_disable_turns_the_second_factor_off(db: Session) -> None:
    user = _user(db)
    _enrol_and_activate(db, user)
    mfa.disable(db, user_id=user.id)
    assert mfa.is_active(db, user.id) is False


def test_admin_reset_clears_a_locked_out_account(db: Session) -> None:
    user = _user(db)
    _enrol_and_activate(db, user)
    mfa.admin_reset(db, user_id=user.id)
    assert mfa.is_active(db, user.id) is False


def test_the_login_ticket_round_trips(db: Session) -> None:
    user_id = uuid.uuid4()
    ticket = mfa.mint_mfa_ticket(user_id=user_id, settings=SETTINGS, now=NOW)
    assert mfa.verify_mfa_ticket(ticket, settings=SETTINGS) == user_id


def test_a_tampered_or_foreign_ticket_is_rejected(db: Session) -> None:
    ticket = mfa.mint_mfa_ticket(user_id=uuid.uuid4(), settings=SETTINGS, now=NOW)
    with pytest.raises(UnauthorizedError):
        mfa.verify_mfa_ticket(ticket + "x", settings=SETTINGS)
    other = SimpleNamespace(
        auth_jwt_secret="a-different-secret-0123456789abcdef0123456789",
        auth_jwt_issuer="test-issuer",
        auth_jwt_audience="test-audience",
    )
    with pytest.raises(UnauthorizedError):
        mfa.verify_mfa_ticket(ticket, settings=other)


def test_an_expired_ticket_is_rejected(db: Session) -> None:
    # Minted well in the past so its exp is behind real wall-clock time
    # regardless of when the suite runs (jwt.decode checks the real clock).
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    ticket = mfa.mint_mfa_ticket(user_id=uuid.uuid4(), settings=SETTINGS, now=long_ago)
    with pytest.raises(UnauthorizedError):
        mfa.verify_mfa_ticket(ticket, settings=SETTINGS)


def test_an_access_token_cannot_be_replayed_as_a_ticket(db: Session) -> None:
    # The ticket audience is distinct, so a real session token fails ticket
    # verification and vice versa.
    from shared_python.auth.security import create_access_token

    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        username="alice",
        secret_key=SETTINGS.auth_jwt_secret,
        issuer=SETTINGS.auth_jwt_issuer,
        audience=SETTINGS.auth_jwt_audience,
        expires_minutes=60,
    )
    with pytest.raises(UnauthorizedError):
        mfa.verify_mfa_ticket(token, settings=SETTINGS)
