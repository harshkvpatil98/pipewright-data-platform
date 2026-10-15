"""Reversible tokens: replace a value with a token only this deployment can turn back.

A pseudonym (`privacy.pseudonymise`) is one way; a token can be revealed, by an
administrator, through Administration, and every reveal is audited. Tokens are
**deterministic**: the same value under the same key name always gives the
same token, so a run and its replay agree, tokens still join and group, and a
reveal needs nothing stored.

AES-SIV (RFC 5297) with a 512-bit key derived by HKDF-SHA256 from the
deployment's `APP_SECRET_ENCRYPTION_KEY` and the key name. SIV is the
standard construction for deterministic authenticated encryption: equal
values give equal tokens, which is the point here and what it promises; a
tampered token fails to reveal rather than revealing something else.
"""

from __future__ import annotations

import base64
import os

from shared_python.errors import BadRequestError, MisconfiguredEnvironmentError

PREFIX = "tok_"


def _key(name: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    secret = os.getenv("APP_SECRET_ENCRYPTION_KEY", "").strip()
    if not secret:
        raise MisconfiguredEnvironmentError(
            "Reversible tokens need APP_SECRET_ENCRYPTION_KEY, the key this deployment encrypts its secrets with.")
    if not name or len(name) > 100:
        raise BadRequestError("Name the token key (up to 100 characters).")
    return HKDF(algorithm=hashes.SHA256(), length=64, salt=b"pipewright-reversible-token-v1",
                info=name.encode("utf-8")).derive(secret.encode("utf-8"))


def tokenise(value: str, key_name: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESSIV

    sealed = AESSIV(_key(key_name)).encrypt(str(value).encode("utf-8"), None)
    return PREFIX + base64.urlsafe_b64encode(sealed).decode("ascii").rstrip("=")


def reveal(token: str, key_name: str) -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESSIV

    if not isinstance(token, str) or not token.startswith(PREFIX):
        raise BadRequestError("That is not a token this deployment made: tokens start with tok_.")
    body = token[len(PREFIX):]
    try:
        sealed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        return AESSIV(_key(key_name)).decrypt(sealed, None).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise BadRequestError(
            "That token does not reveal under this key name: it was changed, or made with another key.") from exc
