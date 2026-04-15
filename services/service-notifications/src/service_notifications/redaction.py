from __future__ import annotations

from typing import Any

from service_notifications.constants import EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK


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
