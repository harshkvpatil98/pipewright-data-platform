"""One-time codes that set a password: account activation and admin reset.

The plaintext is returned once — a real deployment emails it; here the admin
hands it over — and only its hash is stored. A code is single use, short
lived, and bound to a purpose, so an activation code cannot be spent as a
password reset and a used or expired code is inert.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError

from service_auth.models import AuthCode

ACTIVATION = "activation"
RESET = "reset"
_PURPOSES = (ACTIVATION, RESET)
DEFAULT_TTL_MINUTES = 30


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def issue_code(
    db: Session, *, user_id: uuid.UUID, purpose: str, ttl_minutes: int = DEFAULT_TTL_MINUTES
) -> str:
    """Create a code for this user and purpose; return the plaintext once.

    Any earlier unused code of the same purpose is spent first, so only the
    most recent one works — a reissued reset must invalidate the previous.
    """
    if purpose not in _PURPOSES:
        raise BadRequestError(f"Purpose must be one of: {', '.join(_PURPOSES)}.")

    now = datetime.now(UTC)
    for stale in db.scalars(
        select(AuthCode).where(
            AuthCode.user_id == user_id,
            AuthCode.purpose == purpose,
            AuthCode.used_at.is_(None),
        )
    ):
        stale.used_at = now

    plaintext = secrets.token_urlsafe(18)
    db.add(
        AuthCode(
            user_id=user_id,
            purpose=purpose,
            code_hash=_hash(plaintext),
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
    )
    db.commit()
    return plaintext


def redeem_code(
    db: Session, *, code: str, purpose: str | None = None
) -> tuple[uuid.UUID, str]:
    """Spend a code, returning (user_id, purpose), or refuse with a reason.

    `purpose=None` accepts a code of any purpose — the login screen has one
    "set a password with your code" field and does not know whether the code
    was an activation or a reset. The same message covers unknown, expired and
    already-used codes so a caller cannot probe which state a code is in.
    """
    query = select(AuthCode).where(AuthCode.code_hash == _hash(code))
    if purpose is not None:
        query = query.where(AuthCode.purpose == purpose)
    record = db.scalar(query)
    now = datetime.now(UTC)
    invalid = BadRequestError("This code is invalid, expired, or already used.")
    if record is None or record.used_at is not None:
        raise invalid
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < now:
        raise invalid
    record.used_at = now
    db.commit()
    return record.user_id, record.purpose
