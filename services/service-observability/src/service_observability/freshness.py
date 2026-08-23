"""Freshness SLAs: "orders must be under six hours old".

Staleness is the failure mode that reports nothing. A pipeline that stopped
running produces no errors, no failed rules, and no drift -- yesterday's
numbers simply keep being served as though they were today's. The only way to
catch it is to assert the absence: check that something *did* happen recently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MIN_MAX_AGE_MINUTES = 1
# A year. Beyond this a freshness policy is not expressing anything.
MAX_MAX_AGE_MINUTES = 525_600

SEVERITIES = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class FreshnessVerdict:
    status: str  # "fresh" | "stale" | "unknown"
    age_minutes: float | None
    max_age_minutes: int
    overdue_minutes: float
    explanation: str

    @property
    def is_breach(self) -> bool:
        return self.status == "stale"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "age_minutes": self.age_minutes,
            "max_age_minutes": self.max_age_minutes,
            "overdue_minutes": self.overdue_minutes,
            "explanation": self.explanation,
        }


def humanise_minutes(minutes: float) -> str:
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        count = int(round(minutes))
        return f"{count} minute" + ("" if count == 1 else "s")
    if minutes < 60 * 24:
        hours = minutes / 60
        return f"{hours:.1f} hours" if hours < 10 else f"{int(round(hours))} hours"
    days = minutes / (60 * 24)
    return f"{days:.1f} days" if days < 10 else f"{int(round(days))} days"


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def evaluate_freshness(
    *,
    last_updated_at: datetime | None,
    max_age_minutes: int,
    now: datetime | None = None,
) -> FreshnessVerdict:
    """Compare a dataset's age against its promise."""
    moment = _as_utc(now or datetime.now(UTC))

    if last_updated_at is None:
        return FreshnessVerdict(
            status="unknown",
            age_minutes=None,
            max_age_minutes=max_age_minutes,
            overdue_minutes=0.0,
            explanation="This dataset has never recorded an update, so its age cannot be checked.",
        )

    age_minutes = (moment - _as_utc(last_updated_at)).total_seconds() / 60
    if age_minutes < 0:
        # A clock skew between writer and checker; treat as just-updated rather
        # than reporting a negative age nobody can act on.
        age_minutes = 0.0

    if age_minutes <= max_age_minutes:
        return FreshnessVerdict(
            status="fresh",
            age_minutes=round(age_minutes, 2),
            max_age_minutes=max_age_minutes,
            overdue_minutes=0.0,
            explanation=(
                f"Updated {humanise_minutes(age_minutes)} ago, within the "
                f"{humanise_minutes(max_age_minutes)} limit."
            ),
        )

    overdue = age_minutes - max_age_minutes
    return FreshnessVerdict(
        status="stale",
        age_minutes=round(age_minutes, 2),
        max_age_minutes=max_age_minutes,
        overdue_minutes=round(overdue, 2),
        explanation=(
            f"Last updated {humanise_minutes(age_minutes)} ago, which is "
            f"{humanise_minutes(overdue)} past the {humanise_minutes(max_age_minutes)} limit."
        ),
    )
