"""Renewing a sign-in session while it is in use.

The properties a security review asks about: renewal never outlives the
session limit, never revives a session that was ended (sign-out-everywhere,
deactivation, expiry), and never applies to API tokens.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth import session as session_service
from service_auth.models import User
from service_auth.service import sign_out_everywhere
from shared_python.auth.security import create_access_token, decode_access_token, hash_password
from shared_python.errors import BadRequestError, UnauthorizedError

SETTINGS = SimpleNamespace(
    auth_jwt_secret="test-secret-that-is-long-enough-0123456789",
    auth_jwt_issuer="issuer",
    auth_jwt_audience="audience",
    auth_access_token_exp_minutes=60,
    auth_session_max_hours=12,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    from shared_python.db import Base

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db: Session) -> User:
    user = User(username="alice", password_hash=hash_password("correct horse battery"), role="viewer", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User, *, auth_time: int | None = None) -> str:
    token, _ = create_access_token(
        user_id=str(user.id),
        username=user.username,
        secret_key=SETTINGS.auth_jwt_secret,
        issuer=SETTINGS.auth_jwt_issuer,
        audience=SETTINGS.auth_jwt_audience,
        expires_minutes=SETTINGS.auth_access_token_exp_minutes,
        token_version=user.token_version,
        auth_time=auth_time,
    )
    return token


def _decode(token: str):
    return decode_access_token(
        token, secret_key=SETTINGS.auth_jwt_secret, issuer=SETTINGS.auth_jwt_issuer, audience=SETTINGS.auth_jwt_audience
    )


def test_a_valid_session_gets_a_fresh_token_that_keeps_its_sign_in_time(db: Session) -> None:
    user = _user(db)
    signed_in = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    fresh, expires_in, renewed_for = session_service.renew(db, presented=_token(user, auth_time=signed_in), settings=SETTINGS)
    payload = _decode(fresh)
    assert renewed_for.id == user.id
    assert expires_in == 3600
    assert payload.auth_time == signed_in
    assert payload.exp > datetime.now(UTC).timestamp() + 3500


def test_renewal_stops_at_the_session_limit(db: Session) -> None:
    user = _user(db)
    signed_in = int((datetime.now(UTC) - timedelta(hours=12, minutes=1)).timestamp())
    with pytest.raises(UnauthorizedError, match="signed in for a long time"):
        session_service.renew(db, presented=_token(user, auth_time=signed_in), settings=SETTINGS)


def test_a_session_ended_everywhere_cannot_be_renewed(db: Session) -> None:
    user = _user(db)
    token = _token(user)
    sign_out_everywhere(db, user_id=user.id)
    with pytest.raises(UnauthorizedError, match="session has ended"):
        session_service.renew(db, presented=token, settings=SETTINGS)


def test_a_deactivated_account_cannot_renew(db: Session) -> None:
    user = _user(db)
    token = _token(user)
    user.is_active = False
    db.commit()
    with pytest.raises(UnauthorizedError):
        session_service.renew(db, presented=token, settings=SETTINGS)


def test_an_expired_token_cannot_be_renewed(db: Session) -> None:
    user = _user(db)
    past = datetime.now(UTC) - timedelta(minutes=5)
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "username": user.username,
            "iss": SETTINGS.auth_jwt_issuer,
            "aud": SETTINGS.auth_jwt_audience,
            "exp": int(past.timestamp()),
            "ver": user.token_version,
        },
        SETTINGS.auth_jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        session_service.renew(db, presented=expired, settings=SETTINGS)


def test_an_api_token_is_not_a_session(db: Session) -> None:
    _user(db)
    with pytest.raises(BadRequestError):
        session_service.renew(db, presented="pw_abcdefghijklmnopqrstuvwxyz", settings=SETTINGS)


def test_a_token_from_before_sign_in_times_counts_from_one_lifetime_before_expiry(db: Session) -> None:
    user = _user(db)
    now = datetime.now(UTC)
    legacy = jwt.encode(
        {
            "sub": str(user.id),
            "username": user.username,
            "iss": SETTINGS.auth_jwt_issuer,
            "aud": SETTINGS.auth_jwt_audience,
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "ver": user.token_version,
        },
        SETTINGS.auth_jwt_secret,
        algorithm="HS256",
    )
    fresh, _, _ = session_service.renew(db, presented=legacy, settings=SETTINGS)
    # Issued 30 minutes ago by that reckoning, so the sign-in time is kept as such.
    assert abs(_decode(fresh).auth_time - (now - timedelta(minutes=30)).timestamp()) < 5
