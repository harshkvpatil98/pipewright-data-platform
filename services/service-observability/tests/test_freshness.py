"""Freshness SLAs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from service_observability.freshness import evaluate_freshness, humanise_minutes

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_a_recent_update_is_fresh():
    verdict = evaluate_freshness(
        last_updated_at=NOW - timedelta(hours=2), max_age_minutes=360, now=NOW
    )
    assert verdict.status == "fresh"
    assert verdict.overdue_minutes == 0.0
    assert "within the" in verdict.explanation


def test_an_old_update_is_stale_and_says_by_how_much():
    verdict = evaluate_freshness(
        last_updated_at=NOW - timedelta(hours=9), max_age_minutes=360, now=NOW
    )
    assert verdict.is_breach
    assert verdict.overdue_minutes == 180.0
    assert "past the" in verdict.explanation


def test_exactly_at_the_limit_is_still_fresh():
    verdict = evaluate_freshness(
        last_updated_at=NOW - timedelta(minutes=360), max_age_minutes=360, now=NOW
    )
    assert verdict.status == "fresh"


def test_a_dataset_that_never_updated_is_unknown_not_stale():
    """Unknown and stale are different problems and need different responses."""
    verdict = evaluate_freshness(last_updated_at=None, max_age_minutes=60, now=NOW)
    assert verdict.status == "unknown"
    assert verdict.is_breach is False


def test_a_naive_timestamp_is_read_as_utc():
    verdict = evaluate_freshness(
        last_updated_at=datetime(2026, 8, 21, 11, 0), max_age_minutes=120, now=NOW
    )
    assert verdict.status == "fresh"
    assert verdict.age_minutes == 60.0


def test_clock_skew_does_not_produce_a_negative_age():
    verdict = evaluate_freshness(
        last_updated_at=NOW + timedelta(minutes=5), max_age_minutes=60, now=NOW
    )
    assert verdict.age_minutes == 0.0
    assert verdict.status == "fresh"


def test_durations_read_the_way_a_person_would_say_them():
    assert humanise_minutes(0.5) == "less than a minute"
    assert humanise_minutes(1) == "1 minute"
    assert humanise_minutes(45) == "45 minutes"
    assert humanise_minutes(150) == "2.5 hours"
    assert humanise_minutes(60 * 30) == "1.2 days"
