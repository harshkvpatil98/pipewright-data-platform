from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from service_schedules.due import (
    compute_first_next_run_utc,
    compute_next_run_after_utc,
    resolve_schedule_timezone,
)


def test_resolve_schedule_timezone_invalid_falls_back_utc() -> None:
    assert str(resolve_schedule_timezone("Not/A/Zone")) == "UTC"


def test_compute_first_next_run_utc_is_in_future() -> None:
    tz = ZoneInfo("UTC")
    base = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
    nxt = compute_first_next_run_utc("*/15 * * * *", tz, now_utc=base)
    assert nxt > base
    assert nxt.tzinfo == UTC


def test_compute_next_run_after_advances() -> None:
    tz = ZoneInfo("UTC")
    due = datetime(2030, 6, 1, 9, 0, 0, tzinfo=UTC)
    nxt = compute_next_run_after_utc("0 9 * * *", tz, due)
    assert nxt > due
    assert nxt.hour == 9
