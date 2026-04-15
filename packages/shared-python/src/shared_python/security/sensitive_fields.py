from __future__ import annotations

# Keys inside destination_configs / BI configs (same table) that must be encrypted at rest.
DESTINATION_SENSITIVE_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "postgres": ("password",),
    "s3": ("secret_access_key",),
    "local_export": (),
    "power_bi": ("client_secret",),
    "tableau": ("password", "personal_access_token_secret"),
}

# external_notification_targets.config_json
NOTIFICATION_TARGET_SENSITIVE_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "email": (),
    "slack_webhook": ("webhook_url",),
}
