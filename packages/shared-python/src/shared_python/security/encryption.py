from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from shared_python.errors import MisconfiguredEnvironmentError

STORED_SECRET_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    raw = os.getenv("APP_SECRET_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise MisconfiguredEnvironmentError(
            "APP_SECRET_ENCRYPTION_KEY is not set. Generate a Fernet key with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except ValueError as exc:
        raise MisconfiguredEnvironmentError(
            "APP_SECRET_ENCRYPTION_KEY must be a valid Fernet key (url-safe base64-encoded 32-byte key)."
        ) from exc


def encrypt_secret_value(plaintext: str) -> str:
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a string")
    if plaintext.startswith(STORED_SECRET_PREFIX):
        return plaintext
    f = _fernet()
    token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{STORED_SECRET_PREFIX}{token}"


def decrypt_secret_value(stored: str) -> str:
    if not isinstance(stored, str) or not stored.startswith(STORED_SECRET_PREFIX):
        return stored
    token = stored[len(STORED_SECRET_PREFIX) :]
    f = _fernet()
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise MisconfiguredEnvironmentError(
            "Could not decrypt a stored secret. APP_SECRET_ENCRYPTION_KEY may be wrong or the value corrupted."
        ) from exc
