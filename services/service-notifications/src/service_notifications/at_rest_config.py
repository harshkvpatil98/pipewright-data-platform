from __future__ import annotations

from typing import Any

from shared_python.security.config_crypto import decrypt_sensitive_fields, encrypt_sensitive_fields
from shared_python.security.sensitive_fields import NOTIFICATION_TARGET_SENSITIVE_FIELD_KEYS


def persist_notification_target_config_at_rest(target_type: str, validated_config: dict[str, Any]) -> dict[str, Any]:
    keys = NOTIFICATION_TARGET_SENSITIVE_FIELD_KEYS.get(target_type, ())
    return encrypt_sensitive_fields(dict(validated_config), keys)


def notification_target_config_for_internal_use(target_type: str, stored: dict[str, Any]) -> dict[str, Any]:
    keys = NOTIFICATION_TARGET_SENSITIVE_FIELD_KEYS.get(target_type, ())
    return decrypt_sensitive_fields(dict(stored), keys)
