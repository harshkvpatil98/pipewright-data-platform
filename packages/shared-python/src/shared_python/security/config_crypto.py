"""Sensitive config fields, encrypted at rest and resolved at the point of use.

A field can hold two things now: a value, encrypted with this deployment's key,
or a *reference* to a secret store -- `vault://database/prod#password`. The two
are interchangeable from a connector's point of view, which is what lets a
deployment move its secrets into Vault without every connector learning about
Vault. See `shared_python.security.vault`.
"""

from __future__ import annotations

from typing import Any

from shared_python.security.encryption import decrypt_secret_value, encrypt_secret_value
from shared_python.security.vault import parse_reference, resolve


def encrypt_sensitive_fields(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    out = dict(config)
    for name in field_names:
        v = out.get(name)
        if isinstance(v, str) and v:
            # A reference is a pointer, not a secret. Encrypting it would hide
            # from an operator which store a connection actually reads from.
            if parse_reference(v) is not None:
                continue
            out[name] = encrypt_secret_value(v)
    return out


def decrypt_sensitive_fields(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    """The usable config: ciphertext decrypted, references fetched.

    Both happen here, at the point of use, so a caller never has to know which
    of the two a field held.
    """
    out = dict(config)
    for name in field_names:
        v = out.get(name)
        if isinstance(v, str) and v:
            out[name] = resolve(v) if parse_reference(v) is not None else decrypt_secret_value(v)
    return out
