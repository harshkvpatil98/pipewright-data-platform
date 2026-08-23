from __future__ import annotations

from typing import Any

import httpx

from shared_python.logging import get_logger

logger = get_logger(__name__)


def _payload_text(*, title: str, message: str, level: str, event_type: str | None) -> str:
    parts = [f"*{title}*", message]
    if event_type:
        parts.append(f"_event: `{event_type}` · level: {level}_")
    return "\n\n".join(parts)


def send_slack_test_message(*, config: dict[str, Any]) -> tuple[bool, str]:
    text = "Test notification from the Pipewright (external target)."
    return _post_webhook(config=config, text=text)


def send_slack_event_message(
    *,
    config: dict[str, Any],
    title: str,
    message: str,
    level: str,
    event_type: str,
) -> tuple[bool, str]:
    label = config.get("channel_label")
    header = f"[{label}] " if isinstance(label, str) and label.strip() else ""
    text = header + _payload_text(title=title, message=message, level=level, event_type=event_type)
    return _post_webhook(config=config, text=text)


def _post_webhook(*, config: dict[str, Any], text: str) -> tuple[bool, str]:
    url = config.get("webhook_url")
    if not isinstance(url, str) or not url.strip():
        return False, "webhook_url missing."

    body = {"text": text[:15000]}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url.strip(), json=body)
    except httpx.HTTPError as e:
        logger.warning("slack_webhook_http_error", extra={"error_type": type(e).__name__})
        return False, f"Webhook request failed: {e}"

    if r.status_code >= 400:
        logger.warning("slack_webhook_bad_status", extra={"status_code": r.status_code})
        return False, f"Webhook returned HTTP {r.status_code}."

    return True, "Slack webhook accepted the message."
