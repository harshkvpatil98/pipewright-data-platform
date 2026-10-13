"""Keeping a signed-in session alive while someone is using it.

A sign-in token lasts `auth_access_token_exp_minutes`. Without renewal, a person
working in the app was signed out every hour, mid-task, whatever they were
doing. The web app renews the token while it is in use, and this module decides
whether a renewal is allowed: only for a sign-in token (never an API token),
only while it is still valid (signature, expiry, account active, not signed out
everywhere), and only up to `auth_session_max_hours` after the person actually
signed in. Past that they sign in again, which is the point of a session limit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.service import get_user_by_id
from service_auth.tokens import looks_like_api_token
from shared_python.auth.security import create_access_token, decode_access_token
from shared_python.errors import BadRequestError, UnauthorizedError

DEFAULT_MAX_HOURS = 12


def renew(db: Session, *, presented: str, settings, now: datetime | None = None) -> tuple[str, int, User]:
    """A fresh token for the session `presented` belongs to: (token, seconds, user)."""
    if looks_like_api_token(presented):
        raise BadRequestError("An API token does not expire this way, so there is nothing to renew.")
    token = decode_access_token(
        presented,
        secret_key=settings.auth_jwt_secret,
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
    )
    user = get_user_by_id(db, uuid.UUID(token.sub))
    if user is None or not user.is_active:
        raise UnauthorizedError("Authenticated user is no longer available.")
    if token.ver != user.token_version:
        raise UnauthorizedError("This session has ended. Sign in again.")

    ttl_minutes = settings.auth_access_token_exp_minutes
    # A token from before `auth_time` existed was issued one lifetime before it
    # expires; that is the latest its sign-in can have been.
    signed_in_at = token.auth_time if token.auth_time is not None else token.exp - ttl_minutes * 60
    limit_hours = getattr(settings, "auth_session_max_hours", DEFAULT_MAX_HOURS)
    current = (now or datetime.now(UTC)).timestamp()
    if current - signed_in_at > limit_hours * 3600:
        raise UnauthorizedError("You have been signed in for a long time. Sign in again to carry on.")

    fresh, expires_in = create_access_token(
        user_id=str(user.id),
        username=user.username,
        secret_key=settings.auth_jwt_secret,
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        expires_minutes=ttl_minutes,
        token_version=user.token_version,
        auth_time=signed_in_at,
    )
    return fresh, expires_in, user
