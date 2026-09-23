"""Runtime heartbeats: is the background worker actually alive?

These pin the leading signal P0 lacked. The read side must distinguish three
states a queue-age guess could not: a fresh beat (alive), a stale beat (a
worker that died), and no beat at all (a component that never started).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared_python.db import Base

from service_observability.runtime import (
    EXPECTED_COMPONENTS,
    record_heartbeat,
    runtime_components,
)

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _by_component(entries: list[dict]) -> dict[str, dict]:
    return {e["component"]: e for e in entries}


def test_a_component_that_never_beat_shows_as_absent_and_unhealthy(db: Session) -> None:
    entries = _by_component(runtime_components(db, now=NOW))
    for component in EXPECTED_COMPONENTS:
        assert component in entries, component
        assert entries[component]["status"] == "absent"
        assert entries[component]["healthy"] is False
        assert entries[component]["last_beat_at"] is None


def test_a_fresh_beat_reads_healthy(db: Session) -> None:
    record_heartbeat(
        db, component="workflow-worker", host="h1", interval_seconds=5, now=NOW
    )
    entries = _by_component(runtime_components(db, now=NOW + timedelta(seconds=3)))
    worker = entries["workflow-worker"]
    assert worker["healthy"] is True
    assert worker["host"] == "h1"
    assert worker["age_seconds"] == pytest.approx(3.0, abs=0.5)


def test_a_stale_beat_reads_unhealthy(db: Session) -> None:
    # Interval 5s → stale after max(30, 15) = 30s. A beat 90s old is dead.
    record_heartbeat(
        db, component="workflow-worker", host="h1", interval_seconds=5, now=NOW
    )
    entries = _by_component(runtime_components(db, now=NOW + timedelta(seconds=90)))
    assert entries["workflow-worker"]["healthy"] is False


def test_a_slow_ticker_is_not_called_dead_between_beats(db: Session) -> None:
    # A 30s ticker beating 40s ago is within max(30, 90) = 90s and still alive.
    record_heartbeat(
        db, component="schedule-ticker", host="h1", interval_seconds=30, now=NOW
    )
    entries = _by_component(runtime_components(db, now=NOW + timedelta(seconds=40)))
    assert entries["schedule-ticker"]["healthy"] is True


def test_beats_are_upserted_per_component_host(db: Session) -> None:
    record_heartbeat(db, component="workflow-worker", host="h1", now=NOW)
    record_heartbeat(
        db, component="workflow-worker", host="h1", now=NOW + timedelta(seconds=5)
    )
    # Same (component, host) updates one row rather than piling up.
    workers = [e for e in runtime_components(db, now=NOW) if e["component"] == "workflow-worker"]
    assert len(workers) == 1

    record_heartbeat(db, component="workflow-worker", host="h2", now=NOW)
    workers = [e for e in runtime_components(db, now=NOW) if e["component"] == "workflow-worker"]
    assert len(workers) == 2  # a second replica gets its own row


def test_stopping_status_is_never_healthy(db: Session) -> None:
    record_heartbeat(
        db, component="workflow-worker", host="h1", status="stopping", now=NOW
    )
    entries = _by_component(runtime_components(db, now=NOW))
    assert entries["workflow-worker"]["healthy"] is False
