"""API tokens: long-lived, scoped, revocable credentials.

The secret is shown once and stored only as a SHA-256 hash, so a leaked
database yields nothing usable. A token authenticates as its owning user, with
its scope capping what that session may do regardless of the user's role — a
`read` token cannot mutate even for an admin.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, NotFoundError, UnauthorizedError

from service_auth.models import ApiToken, User

SCOPES = ("read", "write", "admin")
_TOKEN_BYTES = 24  # 32 url-safe chars of secret beyond the visible prefix

# Which HTTP methods each scope may perform. Read is strictly non-mutating.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """Return (full_token, prefix, token_hash). The full token is shown once."""
    prefix = "pw_" + secrets.token_hex(4)
    secret = secrets.token_urlsafe(_TOKEN_BYTES)
    full = f"{prefix}_{secret}"
    return full, prefix, _hash(full)


def looks_like_api_token(value: str) -> bool:
    """A cheap check so ordinary JWTs never hit the token table."""
    return value.startswith("pw_")


def create_api_token(
    db: Session, *, user_id: uuid.UUID, name: str, scope: str
) -> tuple[ApiToken, str]:
    if scope not in SCOPES:
        raise BadRequestError(f"Scope must be one of: {', '.join(SCOPES)}.")
    if not name.strip():
        raise BadRequestError("Give the token a name so it can be recognised later.")
    full, prefix, token_hash = generate_token()
    record = ApiToken(
        user_id=user_id, name=name.strip(), prefix=prefix, token_hash=token_hash, scope=scope
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, full


def list_api_tokens(db: Session, *, user_id: uuid.UUID) -> list[ApiToken]:
    return list(
        db.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == user_id)
            .order_by(ApiToken.created_at.desc())
        ).all()
    )


def revoke_api_token(db: Session, *, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    token = db.scalar(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    if token is None:
        raise NotFoundError("Token not found.")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        db.commit()


def authenticate_api_token(db: Session, presented: str) -> tuple[User, str]:
    """Resolve a presented token to its (active user, scope), or refuse.

    Records `last_used_at` on success so a stale token is visible in the list.
    """
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(presented)))
    if token is None or token.revoked_at is not None:
        raise UnauthorizedError("Invalid or revoked API token.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("The account this token belongs to is unavailable.")
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return user, token.scope


def scope_allows(scope: str, method: str) -> bool:
    """Whether a token of this scope may make a request with this method."""
    if scope == "read":
        return method.upper() in _READ_METHODS
    # write and admin may both mutate; the admin-only distinction is enforced
    # where admin routes are (role check), not by HTTP method here.
    return True
