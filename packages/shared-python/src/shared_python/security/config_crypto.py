from __future__ import annotations

from typing import Any

from shared_python.security.encryption import decrypt_secret_value, encrypt_secret_value


def encrypt_sensitive_fields(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    out = dict(config)
    for name in field_names:
        v = out.get(name)
        if isinstance(v, str) and v:
            out[name] = encrypt_secret_value(v)
    return out


def decrypt_sensitive_fields(config: dict[str, Any], field_names: tuple[str, ...]) -> dict[str, Any]:
    out = dict(config)
    for name in field_names:
        v = out.get(name)
        if isinstance(v, str) and v:
            out[name] = decrypt_secret_value(v)
    return out
