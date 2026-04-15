from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from service_notifications.constants import (
    ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES,
    ALLOWED_EXTERNAL_TARGET_TYPES,
    EXTERNAL_TARGET_EMAIL,
    EXTERNAL_TARGET_SLACK_WEBHOOK,
)
from shared_python.security.encryption import STORED_SECRET_PREFIX

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_valid_email(value: str) -> bool:
    s = value.strip()
    return bool(_EMAIL_RE.match(s)) and len(s) <= 320


def validate_subscribed_event_types(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("subscribed_event_types must be a list.")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("Each subscribed event type must be a string.")
        if item not in ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {item}")
        if item not in out:
            out.append(item)
    if not out:
        raise ValueError("Select at least one event type.")
    return out


def validate_target_type(value: str) -> str:
    if value not in ALLOWED_EXTERNAL_TARGET_TYPES:
        raise ValueError(f"Invalid target_type: {value}")
    return value


def _should_preserve_slack_webhook(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return True
    s = value.strip()
    if not s or s == "***":
        return True
    if "…" in s or s.endswith("/***"):
        return True
    return False


def merge_external_notification_config(
    existing: dict[str, Any], incoming: dict[str, Any], *, target_type: str
) -> dict[str, Any]:
    if target_type == EXTERNAL_TARGET_EMAIL:
        return {**existing, **incoming}
    if target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
        out = {**existing, **incoming}
        if "webhook_url" in incoming and _should_preserve_slack_webhook(incoming.get("webhook_url")):
            out["webhook_url"] = existing.get("webhook_url", "")
        return out
    return {**existing, **incoming}


def validate_and_normalize_config(*, target_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("config_json must be an object.")

    if target_type == EXTERNAL_TARGET_EMAIL:
        recipient = config.get("recipient_email")
        if not isinstance(recipient, str) or not _is_valid_email(recipient):
            raise ValueError("recipient_email must be a valid email address.")
        sender = config.get("sender_email")
        if sender is not None:
            if not isinstance(sender, str) or not _is_valid_email(sender):
                raise ValueError("sender_email must be a valid email when provided.")
        prefix = config.get("subject_prefix")
        if prefix is not None:
            if not isinstance(prefix, str) or not prefix.strip():
                raise ValueError("subject_prefix must be a non-empty string when provided.")
            if len(prefix) > 120:
                raise ValueError("subject_prefix is too long.")
        return {
            "recipient_email": recipient.strip().lower(),
            **({"sender_email": str(sender).strip().lower()} if sender else {}),
            **({"subject_prefix": prefix.strip()} if prefix else {}),
        }

    if target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
        url = config.get("webhook_url")
        label = config.get("channel_label")
        if isinstance(url, str) and url.startswith(STORED_SECRET_PREFIX):
            if label is not None:
                if not isinstance(label, str) or len(label) > 120:
                    raise ValueError("channel_label must be a string up to 120 characters.")
            out: dict[str, Any] = {"webhook_url": url}
            if isinstance(label, str) and label.strip():
                out["channel_label"] = label.strip()
            return out
        if not isinstance(url, str) or not url.strip():
            raise ValueError("webhook_url is required.")
        parsed = urlparse(url.strip())
        if parsed.scheme != "https":
            raise ValueError("webhook_url must use https.")
        if not parsed.netloc:
            raise ValueError("webhook_url is invalid.")
        if label is not None:
            if not isinstance(label, str) or len(label) > 120:
                raise ValueError("channel_label must be a string up to 120 characters.")
        return {
            "webhook_url": url.strip(),
            **({"channel_label": label.strip()} if label else {}),
        }

    raise ValueError("Unsupported target_type.")
