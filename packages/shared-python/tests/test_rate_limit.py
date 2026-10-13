"""Rate limits counted in the database (adoption-readiness A7, X5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from shared_python import rate_limit
from shared_python.db import Base
from shared_python.errors import TooManyRequestsError

LIMIT = rate_limit.Limit("test", 3, 60, "tries from here")
NOON = datetime(2026, 10, 14, 12, 0, 10, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[rate_limit.RateLimitWindow.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_the_limit_is_reached_then_says_when_to_try_again(db) -> None:
    for _ in range(3):
        rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON)
    with pytest.raises(TooManyRequestsError) as refused:
        rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON)
    assert refused.value.status_code == 429
    assert refused.value.retry_after == 50  # the window started at 12:00:00
    assert str(refused.value.detail) == "Too many tries from here. Try again in 50 seconds."


def test_each_caller_and_each_window_counts_alone(db) -> None:
    for _ in range(3):
        rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON)
    rate_limit.hit(db, LIMIT, "10.0.0.2", now=NOON)  # someone else
    rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON + timedelta(seconds=60))  # the next minute


def test_limits_can_be_switched_off_for_a_load_test(db, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    for _ in range(10):
        rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON)


def test_old_windows_are_forgotten(db) -> None:
    rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON - timedelta(days=2))
    rate_limit.hit(db, LIMIT, "10.0.0.1", now=NOON)
    assert rate_limit.forget_old_windows(db, now=NOON) == 1
    assert db.scalar(select(func.count()).select_from(rate_limit.RateLimitWindow)) == 1


def test_a_long_wait_is_said_in_minutes() -> None:
    assert rate_limit._wait_in_words(1) == "1 second"
    assert rate_limit._wait_in_words(61) == "2 minutes"
