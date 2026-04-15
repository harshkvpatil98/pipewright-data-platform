from __future__ import annotations

import os


def smtp_configured() -> bool:
    return bool(os.getenv("EXTERNAL_NOTIFICATION_SMTP_HOST", "").strip())


def get_smtp_settings() -> dict[str, str | int | bool | None]:
    return {
        "host": os.getenv("EXTERNAL_NOTIFICATION_SMTP_HOST", "").strip() or None,
        "port": int(os.getenv("EXTERNAL_NOTIFICATION_SMTP_PORT", "587")),
        "user": os.getenv("EXTERNAL_NOTIFICATION_SMTP_USER", "").strip() or None,
        "password": os.getenv("EXTERNAL_NOTIFICATION_SMTP_PASSWORD", "").strip() or None,
        "use_tls": os.getenv("EXTERNAL_NOTIFICATION_SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        "default_from": os.getenv("EXTERNAL_NOTIFICATION_SMTP_FROM", "").strip() or None,
    }
