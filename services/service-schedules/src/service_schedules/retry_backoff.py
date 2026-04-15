from __future__ import annotations

from datetime import datetime, timedelta


def compute_next_retry_at(*, now_utc: datetime, attempt_number: int) -> datetime:
    """Deterministic backoff: 5, 10, 20, ... minutes capped at 120. attempt_number is 1-based."""
    minutes = min(5 * (2 ** (attempt_number - 1)), 120)
    return now_utc + timedelta(minutes=minutes)
