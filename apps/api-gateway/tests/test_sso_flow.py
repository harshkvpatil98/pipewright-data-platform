"""OIDC single sign-on: the flow around the pure logic, provisioning included.

The wire protocol has no live identity provider to run against here, so the
network legs are substituted with fakes and a *real* RS256 ID token signed by a
test key and verified against a matching JWKS -- the signature path is genuine,
only the transport is faked. These pin the parts that are ours to get right:
state is one-time and forgery is rejected, a JIT user is created with the mapped
role, and an existing person is never silently demoted.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway import sso_flow
from service_auth.models import User
from service_enterprise.models import SsoLoginState
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.errors import UnauthorizedError

ISSUER = "https://idp.example.com"
CLIENT_ID = "pipewright-client"
KID = "test-key-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="secret",
        oidc_redirect_uri="https://app.example.com/api/v1/auth/sso/callback",
        oidc_scopes="openid email profile",
        oidc_group_role_map='{"data-admins": "admin"}',
        oidc_default_role="viewer",
        oidc_allow_jit=True,
        auth_jwt_secret="x" * 40,
        auth_jwt_issuer="pipewright",
        auth_jwt_audience="pipewright-web",
        auth_access_token_exp_minutes=60,
        web_base_url="https://app.example.com",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _jwks() -> dict:
    public_jwk = RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key(), as_dict=True)
    public_jwk["kid"] = KID
    public_jwk["alg"] = "RS256"
    return {"keys": [public_jwk]}


def _id_token(*, sub="okta|abc123", email="dana@acme.com", name="Dana Scully", groups=None, nonce=None) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": sub,
        "iat": now,
        "exp": now + 300,
        "email": email,
        "name": name,
        "groups": groups if groups is not None else [],
    }
    if nonce:
        claims["nonce"] = nonce
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


_DISCOVERY = {
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}


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


# ---- configuration ----

def test_is_configured_reflects_the_settings() -> None:
    assert sso_flow.is_configured(_settings()) is True
    assert sso_flow.is_configured(_settings(oidc_issuer=None)) is False


# ---- provisioning ----

def _identity(username="dana@acme.com", role="viewer", email="dana@acme.com", display="Dana"):
    from service_enterprise.sso import MappedIdentity

    return MappedIdentity(
        subject="okta|abc", username=username, email=email, display_name=display, groups=[], role=role
    )


def test_jit_creates_a_user_with_the_mapped_role(db: Session) -> None:
    user = sso_flow.provision_user(db, _identity(role="admin"), settings=_settings())
    assert user.role == "admin"
    assert user.email == "dana@acme.com"
    # SSO users cannot sign in with a password: the hash is random and unusable.
    from shared_python.auth.security import verify_password

    assert verify_password("", user.password_hash) is False


def test_jit_off_refuses_an_unknown_user(db: Session) -> None:
    with pytest.raises(UnauthorizedError):
        sso_flow.provision_user(db, _identity(), settings=_settings(oidc_allow_jit=False))


def test_an_existing_admin_is_not_demoted_by_the_default_role(db: Session) -> None:
    db.add(User(username="dana@acme.com", password_hash=hash_password("x"), role="admin", is_active=True))
    db.commit()
    # The identity carries the default role (no group matched); the admin keeps admin.
    user = sso_flow.provision_user(db, _identity(role="viewer"), settings=_settings())
    assert user.role == "admin"


def test_an_explicit_group_match_updates_an_existing_role(db: Session) -> None:
    db.add(User(username="dana@acme.com", password_hash=hash_password("x"), role="viewer", is_active=True))
    db.commit()
    user = sso_flow.provision_user(db, _identity(role="admin"), settings=_settings())
    assert user.role == "admin"


def test_an_inactive_user_cannot_sign_in(db: Session) -> None:
    db.add(User(username="dana@acme.com", password_hash=hash_password("x"), role="viewer", is_active=False))
    db.commit()
    with pytest.raises(UnauthorizedError):
        sso_flow.provision_user(db, _identity(), settings=_settings())


# ---- the two-request flow ----

def test_begin_login_stores_state_and_returns_a_pkce_url(db: Session) -> None:
    url = sso_flow.begin_login(
        db, settings=_settings(), next_path="/projects", discovery_fetcher=lambda _issuer: _DISCOVERY
    )
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    rows = list(db.scalars(select(SsoLoginState)))
    assert len(rows) == 1 and rows[0].next_path == "/projects"


def test_complete_login_provisions_and_consumes_the_state(db: Session) -> None:
    settings = _settings()
    sso_flow.begin_login(db, settings=settings, next_path="/projects", discovery_fetcher=lambda _i: _DISCOVERY)
    row = db.scalars(select(SsoLoginState)).one()

    user, next_path = sso_flow.complete_login(
        db,
        settings=settings,
        code="auth-code",
        state=row.state,
        discovery_fetcher=lambda _i: _DISCOVERY,
        code_exchanger=lambda **_k: {"id_token": _id_token(groups=["data-admins"], nonce=row.nonce)},
        jwks_fetcher=lambda _u: _jwks(),
    )
    assert user.role == "admin"  # the group mapped to admin
    assert user.email == "dana@acme.com"
    assert next_path == "/projects"
    # One-time: the state row is gone, so a replay finds nothing.
    assert db.scalars(select(SsoLoginState)).first() is None


def test_complete_login_rejects_a_forged_state(db: Session) -> None:
    settings = _settings()
    with pytest.raises(UnauthorizedError):
        sso_flow.complete_login(
            db,
            settings=settings,
            code="auth-code",
            state="never-issued-this",
            discovery_fetcher=lambda _i: _DISCOVERY,
            code_exchanger=lambda **_k: {"id_token": _id_token()},
            jwks_fetcher=lambda _u: _jwks(),
        )


def test_complete_login_rejects_a_token_signed_by_the_wrong_key(db: Session) -> None:
    settings = _settings()
    sso_flow.begin_login(db, settings=settings, discovery_fetcher=lambda _i: _DISCOVERY)
    row = db.scalars(select(SsoLoginState)).one()
    # A JWKS that does not contain the signing key: verification must fail.
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_jwk = RSAAlgorithm.to_jwk(other_key.public_key(), as_dict=True)
    other_jwk["kid"] = KID
    with pytest.raises(UnauthorizedError):
        sso_flow.complete_login(
            db,
            settings=settings,
            code="auth-code",
            state=row.state,
            discovery_fetcher=lambda _i: _DISCOVERY,
            code_exchanger=lambda **_k: {"id_token": _id_token(nonce=row.nonce)},
            jwks_fetcher=lambda _u: {"keys": [other_jwk]},
        )


def test_expired_state_is_rejected(db: Session) -> None:
    settings = _settings()
    sso_flow.begin_login(db, settings=settings, discovery_fetcher=lambda _i: _DISCOVERY)
    row = db.scalars(select(SsoLoginState)).one()
    future = datetime.now(UTC).replace(year=2099)
    with pytest.raises(UnauthorizedError):
        sso_flow.complete_login(
            db, settings=settings, code="c", state=row.state, now=future,
            discovery_fetcher=lambda _i: _DISCOVERY,
            code_exchanger=lambda **_k: {"id_token": _id_token()},
            jwks_fetcher=lambda _u: _jwks(),
        )


def test_sweep_removes_expired_states(db: Session) -> None:
    sso_flow.begin_login(db, settings=_settings(), discovery_fetcher=lambda _i: _DISCOVERY)
    future = datetime.now(UTC).replace(year=2099)
    assert sso_flow.sweep_expired_states(db, now=future) == 1
    assert db.scalars(select(SsoLoginState)).first() is None
