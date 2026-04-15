from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel

from shared_python.errors import UnauthorizedError


class TokenPayload(BaseModel):
    sub: str
    username: str
    exp: int
    iss: str
    aud: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt${}${}".format(
        base64.urlsafe_b64encode(salt).decode("utf-8"),
        base64.urlsafe_b64encode(derived_key).decode("utf-8"),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    algorithm, encoded_salt, encoded_digest = encoded_hash.split("$", 2)
    if algorithm != "scrypt":
        raise UnauthorizedError("Unsupported password hashing algorithm.")
    salt = base64.urlsafe_b64decode(encoded_salt.encode("utf-8"))
    expected_digest = base64.urlsafe_b64decode(encoded_digest.encode("utf-8"))
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return secrets.compare_digest(candidate, expected_digest)


def create_access_token(
    *,
    user_id: str,
    username: str,
    secret_key: str,
    issuer: str,
    audience: str,
    expires_minutes: int,
) -> tuple[str, int]:
    expires_at = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "iss": issuer,
        "aud": audience,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token, expires_minutes * 60


def decode_access_token(token: str, *, secret_key: str, issuer: str, audience: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired access token.") from exc
    return TokenPayload.model_validate(payload)
