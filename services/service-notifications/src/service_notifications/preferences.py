"""Which notifications a person sees one by one, as a daily summary, or not at all.

Every manual run, scheduled run and report used to write its own in-app
notification, and a busy account collected seventy unread messages that said
"succeeded". Failures matter one at a time; routine successes are mostly
reassurance and read best as a running total for the day. Each kind of event
belongs to a category, each category has a sensible default, and a person can
change any of them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_notifications.models import NotificationPreference
from shared_python.errors import BadRequestError

MODES = ("each", "digest", "off")


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    description: str
    default: str


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="failures",
        label="Failures",
        description="A run, schedule or workflow that failed or only partly finished.",
        default="each",
    ),
    Category(
        key="successes",
        label="Routine successes",
        description="Runs that finished without problems.",
        default="digest",
    ),
    Category(
        key="incidents",
        label="Incidents",
        description="Problems that need a person, such as a failed check or late data.",
        default="each",
    ),
    Category(
        key="mentions",
        label="Mentions",
        description="Someone mentioned you in a comment.",
        default="each",
    ),
    Category(
        key="reports",
        label="Reports",
        description="A scheduled report was sent.",
        default="each",
    ),
    Category(
        key="workflows",
        label="Workflow messages",
        description="Messages a workflow sends when it reaches a notify task.",
        default="each",
    ),
)

_BY_KEY = {category.key: category for category in CATEGORIES}


def category_for(event_type: str, level: str) -> str:
    """The category an event belongs to, from its type and level."""
    if event_type == "mention":
        return "mentions"
    if event_type == "incident":
        return "incidents"
    if event_type == "report":
        return "reports"
    if event_type == "workflow":
        return "workflows"
    if event_type.endswith("_failed") or event_type.endswith("_partial") or level in {"error", "warning"}:
        return "failures"
    if event_type.endswith("_succeeded") or level == "success":
        return "successes"
    return "workflows"


def mode_for(db: Session, user_id: uuid.UUID, category: str) -> str:
    stored = db.scalar(
        select(NotificationPreference.mode).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
    )
    if isinstance(stored, str) and stored in MODES:
        return stored
    return _BY_KEY[category].default if category in _BY_KEY else "each"


def all_modes(db: Session, user_id: uuid.UUID) -> dict[str, str]:
    rows = db.execute(
        select(NotificationPreference.category, NotificationPreference.mode).where(
            NotificationPreference.user_id == user_id
        )
    ).all()
    stored = {category: mode for category, mode in rows if mode in MODES}
    return {category.key: stored.get(category.key, category.default) for category in CATEGORIES}


def set_mode(db: Session, user_id: uuid.UUID, category: str, mode: str) -> None:
    if category not in _BY_KEY:
        raise BadRequestError(f"There is no notification category called '{category}'.")
    if mode not in MODES:
        raise BadRequestError(f"'{mode}' is not one of: {', '.join(MODES)}.")
    row = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
    )
    if row is None:
        db.add(NotificationPreference(user_id=user_id, category=category, mode=mode))
    else:
        row.mode = mode
    db.commit()
