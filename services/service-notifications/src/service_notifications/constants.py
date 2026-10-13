from __future__ import annotations

ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "schedule_run_failed",
        "schedule_run_succeeded",
        "dataset_publish_failed",
        "dataset_publish_succeeded",
        "transformation_run_failed",
        "transformation_run_succeeded",
        # A6 (W6): the failures nobody was told about outside the app, and a
        # weekly round-up for whoever wants the trend rather than each event.
        "incident_opened",
        "workflow_run_failed",
        "workflow_run_partial",
        "weekly_summary",
    }
)

EXTERNAL_TARGET_EMAIL = "email"
EXTERNAL_TARGET_SLACK_WEBHOOK = "slack_webhook"

ALLOWED_EXTERNAL_TARGET_TYPES: frozenset[str] = frozenset({EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK})
