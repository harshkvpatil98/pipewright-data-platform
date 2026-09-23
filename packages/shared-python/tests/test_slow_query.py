"""The slow-query logger: off by default, loud only past the threshold.

Diagnostics that are always on are diagnostics nobody reads. These pin that a
threshold of zero installs nothing, a high threshold stays silent on a fast
query, and a low threshold logs the statement when one crosses it.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, text

from shared_python.db.slow_query import install_slow_query_logger


def _run_a_query(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def test_a_zero_threshold_installs_nothing(caplog) -> None:
    engine = create_engine("sqlite://")
    install_slow_query_logger(engine, threshold_ms=0)
    with caplog.at_level(logging.WARNING):
        _run_a_query(engine)
    assert not [r for r in caplog.records if "slow_query" in r.getMessage()]


def test_a_high_threshold_stays_silent_on_a_fast_query(caplog) -> None:
    engine = create_engine("sqlite://")
    install_slow_query_logger(engine, threshold_ms=10_000)
    with caplog.at_level(logging.WARNING):
        _run_a_query(engine)
    assert not [r for r in caplog.records if "slow_query" in r.getMessage()]


def test_a_low_threshold_logs_the_statement(caplog) -> None:
    engine = create_engine("sqlite://")
    # Any real query takes more than a microsecond, so this always trips.
    install_slow_query_logger(engine, threshold_ms=0.0001)
    with caplog.at_level(logging.WARNING):
        _run_a_query(engine)
    slow = [r for r in caplog.records if "slow_query" in r.getMessage()]
    assert slow, "a query over the threshold should be logged"
    message = slow[0].getMessage()
    assert "SELECT 1" in message
    assert "duration_ms=" in message
