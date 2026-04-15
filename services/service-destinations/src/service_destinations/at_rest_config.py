from __future__ import annotations

from typing import Any

from shared_python.security.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields
from shared_python.security.sensitive_fields import DESTINATION_SENSITIVE_FIELD_KEYS


def persist_destination_config_at_rest(destination_type: str, validated_config: dict[str, Any]) -> dict[str, Any]:
    keys = DESTINATION_SENSITIVE_FIELD_KEYS.get(destination_type, ())
    return encrypt_sensitive_fields(dict(validated_config), keys)


def destination_config_for_internal_use(destination_type: str, stored: dict[str, Any]) -> dict[str, Any]:
    keys = DESTINATION_SENSITIVE_FIELD_KEYS.get(destination_type, ())
    return decrypt_sensitive_fields(dict(stored), keys)
