from __future__ import annotations

from typing import Any

from service_notifications.constants import (
    EXTERNAL_TARGET_EMAIL,
    EXTERNAL_TARGET_SLACK_WEBHOOK,
    EXTERNAL_TARGET_WEBHOOK,
)


def redact_config_for_api(*, target_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe for API responses (mask secrets)."""
    if target_type == EXTERNAL_TARGET_EMAIL:
        out = dict(config)
        if "recipient_email" in out and isinstance(out["recipient_email"], str):
            out["recipient_email"] = _mask_email(out["recipient_email"])
        return out
    if target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
        out = dict(config)
        url = out.get("webhook_url")
        if isinstance(url, str):
            out["webhook_url"] = _redact_webhook_url(url)
        return out
    if target_type == EXTERNAL_TARGET_WEBHOOK:
        out = dict(config)
        # Shown once, when made or rotated; afterwards only its last characters.
        secret = out.pop("signing_secret", None)
        out["signing_secret_hint"] = _secret_hint(secret)
        return out
    return dict(config)


def _mask_email(email: str) -> str:
    parts = email.strip().split("@", 1)
    if len(parts) != 2:
        return "***"
    local, domain = parts
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def _redact_webhook_url(url: str) -> str:
    """Show host + path prefix only; never full token path."""
    from urllib.parse import urlparse

    p = urlparse(url)
    path = p.path or ""
    if "hooks.slack.com" in (p.netloc or "") and path.startswith("/services/"):
        return f"https://{p.netloc}{path[:20]}…/***"
    return f"https://{p.netloc}/…/***"


def _secret_hint(stored: object) -> str | None:
    """`whsec_…abcd`: enough to tell two secrets apart, nothing to sign with."""
    if not isinstance(stored, str) or not stored:
        return None
    try:
        from shared_python.security.encryption import decrypt_secret_value

        plain = decrypt_secret_value(stored)
    except Exception:  # noqa: BLE001 - a key problem shows as no hint, not an error
        return None
    return f"whsec_…{plain[-4:]}"
