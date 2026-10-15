"""API tokens: long-lived, scoped, revocable credentials.

The secret is shown once and stored only as a SHA-256 hash, so a leaked
database yields nothing usable. A token authenticates as its owning user, with
its scope capping what that session may do regardless of the user's role — a
`read` token cannot mutate even for an admin.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

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


#: The longest a token can be set to last, in days.
MAX_DAYS = 3650


def create_api_token(
    db: Session, *, user_id: uuid.UUID, name: str, scope: str,
    project_ids: list[uuid.UUID] | None = None, expires_in_days: int | None = None,
) -> tuple[ApiToken, str]:
    """A new token; limited to ``project_ids`` when given, lasting ``expires_in_days`` when given (X2).

    The caller has checked the person can reach each project."""
    if scope not in SCOPES:
        raise BadRequestError(f"Scope must be one of: {', '.join(SCOPES)}.")
    if not name.strip():
        raise BadRequestError("Give the token a name so it can be recognised later.")
    if project_ids is not None and not project_ids:
        raise BadRequestError("A token limited to projects names at least one.")
    if expires_in_days is not None and not 1 <= expires_in_days <= MAX_DAYS:
        raise BadRequestError(f"A token lasts from 1 to {MAX_DAYS:,} days.")
    full, prefix, token_hash = generate_token()
    record = ApiToken(
        user_id=user_id, name=name.strip(), prefix=prefix, token_hash=token_hash, scope=scope,
        project_ids_json=sorted({str(item) for item in project_ids}) if project_ids else None,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
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


def authenticate_api_token(db: Session, presented: str) -> tuple[User, ApiToken]:
    """Resolve a presented token to its (active user, token), or refuse.

    Records `last_used_at` on success so a stale token is visible in the list.
    """
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(presented)))
    if token is None or token.revoked_at is not None:
        raise UnauthorizedError("Invalid or revoked API token.")
    if is_expired(token):
        raise UnauthorizedError(f"This API token expired on {token.expires_at:%d %b %Y}. Make a new one in Your "
                                "settings.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("The account this token belongs to is unavailable.")
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return user, token


def token_owner(db: Session, presented: str) -> uuid.UUID | None:
    """Whose live API token this is, without recording a use; None if it is not one."""
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(presented)))
    if token is None or token.revoked_at is not None or is_expired(token):
        return None
    return token.user_id


def is_expired(token: ApiToken, now: datetime | None = None) -> bool:
    if token.expires_at is None:
        return False
    expires = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=UTC)
    return expires <= (now or datetime.now(UTC))


def token_projects(token: ApiToken) -> frozenset[uuid.UUID] | None:
    return frozenset(uuid.UUID(item) for item in token.project_ids_json) if token.project_ids_json else None


_PROJECT_PATH = re.compile(r"^/api/v\d+/projects/([0-9a-fA-F-]{36})(?:/|$)")
#: Outside its projects, a limited token reads what is the same for everyone
#: (the catalogues) and who it is; nothing that lists or changes other work.
_EVERYONE_READS = ("/api/v1/auth/me", "/api/v1/connectors", "/api/v1/transformations/tools",
                   "/api/v1/transformations/templates", "/api/v1/charts/types", "/api/v1/health", "/api/v1/status")
_EVERYONE_ASKS = ("/api/v1/connectors/test", "/api/v1/transformations/tools/preview",
                  "/api/v1/transformations/tools/regex/test")


def limited_refusal(projects: frozenset[uuid.UUID], method: str, path: str) -> str | None:
    """Why a token limited to ``projects`` may not make this request, or None (X2)."""
    count = len(projects)
    limited = f"This API token is limited to {count} project{'s' if count != 1 else ''}"
    found = _PROJECT_PATH.match(path)
    if found:
        try:
            wanted = uuid.UUID(found.group(1))
        except ValueError:
            return None  # a malformed id is the route's "not found"
        return None if wanted in projects else f"{limited}, and this is another."
    clean = path.rstrip("/")
    if clean == "/api/v1/projects" and method.upper() in _READ_METHODS:
        return None  # the list holds only its projects
    if clean == "/api/v1/auth/tokens" or clean.startswith("/api/v1/auth/tokens/"):
        return None  # tokens within its projects only, as the routes there decide
    if method.upper() in _READ_METHODS and any(clean == item or clean.startswith(item + "/") for item in _EVERYONE_READS):
        return None
    if method.upper() == "POST" and (clean in _EVERYONE_ASKS or re.fullmatch(r"/api/v1/connectors/[a-z0-9_]+/streams",
                                                                              clean)):
        return None
    return f"{limited}; it cannot reach {clean} outside them."


def scope_allows(scope: str, method: str) -> bool:
    """Whether a token of this scope may make a request with this method."""
    if scope == "read":
        return method.upper() in _READ_METHODS
    # write and admin may both mutate; the admin-only distinction is enforced
    # where admin routes are (role check), not by HTTP method here.
    return True
