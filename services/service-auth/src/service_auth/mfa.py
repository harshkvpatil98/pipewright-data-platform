"""Second-factor authentication: enrol, verify, recover, reset.

The password proves you know a secret; the second factor proves you hold a
device. This wires TOTP (see `totp.py`) into the account: a person enrols by
scanning a QR, confirms with a live code before it takes effect, and is given
one-time recovery codes for the day the phone is lost. Login then asks for the
second factor after the password, and an admin can reset a locked-out account.

Two deliberate safety choices:
* **Enrolment is confirmed before it gates login.** A secret generated but never
  verified with a real code would lock the owner out of their own account on the
  next sign-in. `activated` flips only after a code proves the device works.
* **Recovery codes are hashed and single-use.** They are the backdoor for a lost
  device, so they are treated like passwords: shown once, stored hashed, and
  burned when spent.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

from service_auth.models import User, UserMfa
from service_auth.totp import generate_secret, provisioning_uri, qr_svg, verify
from shared_python.errors import BadRequestError, NotFoundError, UnauthorizedError

RECOVERY_CODE_COUNT = 10
#: How long the between-steps login ticket lives. Long enough to open an
#: authenticator app, short enough that a leaked ticket is near-useless.
MFA_TICKET_TTL_SECONDS = 300


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


@dataclass
class EnrollmentChallenge:
    secret: str
    otpauth_uri: str
    qr_svg: str

    def to_dict(self) -> dict:
        return {"secret": self.secret, "otpauth_uri": self.otpauth_uri, "qr_svg": self.qr_svg}


def _row(db, user_id: uuid.UUID) -> UserMfa | None:
    from sqlalchemy import select

    return db.scalar(select(UserMfa).where(UserMfa.user_id == user_id))


def status(db, user_id: uuid.UUID) -> dict:
    row = _row(db, user_id)
    return {
        "enrolled": row is not None,
        "active": bool(row and row.activated),
    }


def is_active(db, user_id: uuid.UUID) -> bool:
    row = _row(db, user_id)
    return bool(row and row.activated)


def begin_enrollment(db, *, user: User, issuer: str) -> EnrollmentChallenge:
    """Start (or restart) enrolment with a fresh secret, not yet active.

    Restarting an unconfirmed enrolment is fine and replaces the pending secret;
    restarting an *active* one is refused, because that is really "disable then
    re-enrol" and should be explicit so a stolen session cannot silently swap
    someone's second factor.
    """
    row = _row(db, user.id)
    if row is not None and row.activated:
        raise BadRequestError("Two-factor is already on. Turn it off before enrolling again.")

    secret = generate_secret()
    if row is None:
        row = UserMfa(user_id=user.id, secret=secret, activated=False)
        db.add(row)
    else:
        row.secret = secret
        row.activated = False
        row.recovery_codes_json = None
    db.commit()

    account = user.email or user.username
    uri = provisioning_uri(secret, account_name=account, issuer=issuer)
    return EnrollmentChallenge(secret=secret, otpauth_uri=uri, qr_svg=qr_svg(uri))


def activate(db, *, user_id: uuid.UUID, code: str, now: datetime | None = None) -> list[str]:
    """Confirm enrolment with a live code and hand back one-time recovery codes."""
    row = _row(db, user_id)
    if row is None:
        raise BadRequestError("Start two-factor enrolment first.")
    if not verify(row.secret, code, timestamp=int(_now(now).timestamp())):
        raise BadRequestError("That code is not right. Check your authenticator and try again.")

    plaintext = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    row.activated = True
    row.activated_at = _now(now)
    row.recovery_codes_json = [{"hash": _hash(code), "used_at": None} for code in plaintext]
    db.commit()
    return plaintext


def _new_recovery_code() -> str:
    # Two groups of five hex chars: easy to read aloud and to type once.
    raw = secrets.token_hex(5)
    return f"{raw[:5]}-{raw[5:]}"


def verify_second_factor(
    db, *, user_id: uuid.UUID, code: str, now: datetime | None = None
) -> bool:
    """A TOTP code, or a recovery code (which is then spent). Either satisfies
    the second factor; a recovery code can be used exactly once."""
    row = _row(db, user_id)
    if row is None or not row.activated:
        # No active second factor means nothing to check -- callers gate on
        # is_active() first, so reaching here with a code is a caller error.
        return False

    if verify(row.secret, code, timestamp=int(_now(now).timestamp())):
        return True

    return _spend_recovery_code(db, row, code, now=now)


def _spend_recovery_code(db, row: UserMfa, code: str, *, now: datetime | None = None) -> bool:
    target = _hash(code)
    # Copy each entry rather than mutate in place: SQLAlchemy compares the JSON
    # column against a snapshot that shares the same dict objects, so an in-place
    # edit would be invisible and never persist. New dicts make the change real.
    entries = [dict(entry) for entry in (row.recovery_codes_json or [])]
    for entry in entries:
        if entry.get("used_at") is None and secrets.compare_digest(str(entry.get("hash")), target):
            entry["used_at"] = _now(now).isoformat()
            row.recovery_codes_json = entries
            db.commit()
            return True
    return False


def remaining_recovery_codes(db, user_id: uuid.UUID) -> int:
    row = _row(db, user_id)
    if row is None or not row.recovery_codes_json:
        return 0
    return sum(1 for entry in row.recovery_codes_json if entry.get("used_at") is None)


def regenerate_recovery_codes(db, *, user_id: uuid.UUID) -> list[str]:
    """Fresh recovery codes, invalidating the old set. Requires active MFA."""
    row = _row(db, user_id)
    if row is None or not row.activated:
        raise BadRequestError("Two-factor is not on for this account.")
    plaintext = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    row.recovery_codes_json = [{"hash": _hash(code), "used_at": None} for code in plaintext]
    db.commit()
    return plaintext


def disable(db, *, user_id: uuid.UUID) -> None:
    """Turn off the second factor. The caller decides what proof to require."""
    row = _row(db, user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def admin_reset(db, *, user_id: uuid.UUID) -> None:
    """An admin clears a locked-out person's second factor so they can sign in
    with their password and re-enrol. Distinct from self-disable so it can be
    audited as an admin action."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    disable(db, user_id=user_id)


# ---- the between-steps login ticket -----------------------------------------

def _ticket_audience(settings) -> str:
    # A distinct audience so a real access token can never be replayed as a
    # ticket, nor a ticket as an access token.
    return f"{settings.auth_jwt_audience}-mfa"


def mint_mfa_ticket(*, user_id: uuid.UUID, settings, now: datetime | None = None) -> str:
    moment = _now(now)
    payload = {
        "sub": str(user_id),
        "purpose": "mfa",
        "iss": settings.auth_jwt_issuer,
        "aud": _ticket_audience(settings),
        "exp": int(moment.timestamp()) + MFA_TICKET_TTL_SECONDS,
        "jti": secrets.token_urlsafe(9),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")


def verify_mfa_ticket(token: str, *, settings) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=_ticket_audience(settings),
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("This sign-in step expired. Start again.") from exc
    if payload.get("purpose") != "mfa":
        raise UnauthorizedError("This sign-in step expired. Start again.")
    return uuid.UUID(str(payload["sub"]))
