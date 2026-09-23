"""The network legs and provisioning that turn the OIDC logic into a sign-in.

`service_enterprise.sso` holds the pure parts -- PKCE, state, ID-token
verification, claim mapping -- all unit-tested. This composes them with the
three things that actually touch the outside world and the database: fetching
the provider's discovery document and JWKS, exchanging the authorization code
for tokens, and provisioning a user from the verified claims. It lives in the
gateway because that composition needs settings, the HTTP client, and the user
store together.

The three network calls are module-level functions so a test can substitute
them: the wire protocol has no real identity provider to run against here, so it
is exercised against fakes and treated as unverified against a live tenant --
the same honesty the sso module's docstring states.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_enterprise.models import SsoLoginState
from service_enterprise.sso import (
    MappedIdentity,
    ProviderConfig,
    build_authorization_request,
    discovery_url,
    map_identity,
    verify_id_token,
    verify_state,
)
from shared_python.auth.security import hash_password
from shared_python.errors import BadRequestError, UnauthorizedError
from shared_python.logging import get_logger

logger = get_logger(__name__)

STATE_TTL = timedelta(minutes=10)
HTTP_TIMEOUT = 10.0


def is_configured(settings) -> bool:
    """True when enough OIDC settings are present to attempt a sign-in."""
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_redirect_uri)


def _group_role_map(settings) -> dict[str, str]:
    import json

    try:
        parsed = json.loads(settings.oidc_group_role_map or "{}")
        return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


# ---- network legs (substituted in tests) ------------------------------------

def fetch_discovery(issuer: str) -> dict[str, Any]:
    response = httpx.get(discovery_url(issuer), timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def exchange_code(*, token_endpoint: str, data: dict[str, str]) -> dict[str, Any]:
    response = httpx.post(token_endpoint, data=data, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_jwks(jwks_uri: str) -> dict[str, Any]:
    response = httpx.get(jwks_uri, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _config_from_settings(settings, discovery: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
        scopes=tuple((settings.oidc_scopes or "openid email profile").split()),
        authorization_endpoint=discovery.get("authorization_endpoint"),
        token_endpoint=discovery.get("token_endpoint"),
        jwks_uri=discovery.get("jwks_uri"),
        group_role_map=_group_role_map(settings),
        default_role=settings.oidc_default_role,
        allow_jit_provisioning=settings.oidc_allow_jit,
    )


# ---- the two-request flow ---------------------------------------------------

def begin_login(
    db: Session,
    *,
    settings,
    next_path: str = "/",
    discovery_fetcher: Callable[[str], dict[str, Any]] = fetch_discovery,
    now: datetime | None = None,
) -> str:
    """Discover the provider, build the PKCE authorization request, persist its
    state, and return the URL to redirect the browser to."""
    if not is_configured(settings):
        raise BadRequestError("Single sign-on is not configured on this deployment.")
    discovery = discovery_fetcher(settings.oidc_issuer)
    config = _config_from_settings(settings, discovery)
    request = build_authorization_request(config)

    moment = now or datetime.now(UTC)
    db.add(
        SsoLoginState(
            state=request.state,
            code_verifier=request.code_verifier,
            nonce=request.nonce,
            next_path=next_path if next_path.startswith("/") else "/",
            expires_at=moment + STATE_TTL,
        )
    )
    db.commit()
    return request.url


def complete_login(
    db: Session,
    *,
    settings,
    code: str,
    state: str,
    discovery_fetcher: Callable[[str], dict[str, Any]] = fetch_discovery,
    code_exchanger: Callable[..., dict[str, Any]] = exchange_code,
    jwks_fetcher: Callable[[str], dict[str, Any]] = fetch_jwks,
    now: datetime | None = None,
) -> tuple[User, str]:
    """Verify the callback, exchange the code, verify the ID token, and
    provision the user. Returns (user, next_path). The row is consumed so a
    state cannot be replayed."""
    if not is_configured(settings):
        raise BadRequestError("Single sign-on is not configured on this deployment.")

    row = db.scalar(select(SsoLoginState).where(SsoLoginState.state == state))
    # verify_state rejects a missing/forged state in constant time.
    verify_state(row.state if row else None, state)
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if expires < (now or datetime.now(UTC)):
        db.delete(row)
        db.commit()
        raise UnauthorizedError("This sign-in took too long. Start again.")

    verifier, nonce, next_path = row.code_verifier, row.nonce, row.next_path
    # One-time: consume the state before doing anything a replay could repeat.
    db.delete(row)
    db.commit()

    discovery = discovery_fetcher(settings.oidc_issuer)
    config = _config_from_settings(settings, discovery)

    tokens = code_exchanger(
        token_endpoint=config.token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret or "",
            "code_verifier": verifier,
        },
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise UnauthorizedError("The provider did not return an ID token.")

    jwks = jwks_fetcher(config.jwks_uri)
    claims = verify_id_token(id_token, config=config, jwks=jwks, nonce=nonce)
    identity = map_identity(claims, config)
    user = provision_user(db, identity, settings=settings)
    return user, next_path


def provision_user(db: Session, identity: MappedIdentity, *, settings) -> User:
    """Find the SSO user, or create one just in time. The identity provider is
    the source of truth for who they are; a group mapping may set their role,
    but an existing person is never silently demoted to the default."""
    existing = db.scalar(select(User).where(User.username == identity.username))
    if existing is not None:
        if not existing.is_active:
            raise UnauthorizedError("This account is inactive.")
        if identity.email:
            existing.email = identity.email
        if identity.display_name:
            existing.display_name = identity.display_name
        # Only an explicit group match changes an existing role, so an empty or
        # non-matching map never demotes someone who was promoted by hand.
        if identity.role != settings.oidc_default_role:
            existing.role = identity.role
        db.commit()
        return existing

    if not settings.oidc_allow_jit:
        raise UnauthorizedError(
            "No account exists for this identity, and automatic provisioning is off."
        )

    user = User(
        username=identity.username,
        # SSO users never sign in with a password; a random unusable hash means
        # the password path can never authenticate them.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=identity.role,
        is_active=True,
        email=identity.email,
        display_name=identity.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def sweep_expired_states(db: Session, *, now: datetime | None = None) -> int:
    """Delete stale login-state rows. Called opportunistically on start."""
    moment = now or datetime.now(UTC)
    rows = list(db.scalars(select(SsoLoginState).where(SsoLoginState.expires_at < moment)).all())
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
