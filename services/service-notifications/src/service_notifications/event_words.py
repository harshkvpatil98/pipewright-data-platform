"""What each event is called in an email subject or a Slack message (A6, W6)."""

from __future__ import annotations

EVENT_WORDS: dict[str, str] = {
    "schedule_run_failed": "A scheduled run failed",
    "schedule_run_succeeded": "A scheduled run finished",
    "dataset_publish_failed": "A delivery failed",
    "dataset_publish_succeeded": "A delivery finished",
    "transformation_run_failed": "A recipe run failed",
    "transformation_run_succeeded": "A recipe run finished",
    "incident_opened": "An incident opened",
    "workflow_run_failed": "A workflow failed",
    "workflow_run_partial": "A workflow finished with problems",
    "weekly_summary": "Weekly summary",
}

LEVEL_WORDS: dict[str, str] = {
    "error": "Needs attention",
    "warning": "Worth a look",
    "success": "Done",
    "info": "For your information",
}


def event_words(event_type: str | None) -> str:
    if not event_type:
        return ""
    return EVENT_WORDS.get(event_type, event_type.replace("_", " ").capitalize())


def level_words(level: str) -> str:
    return LEVEL_WORDS.get(level, level.capitalize())
