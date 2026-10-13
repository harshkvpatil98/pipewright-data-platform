from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from service_destinations.sql_writer import engine_for


def check_mysql_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    """Connect, ask the server's version, and report how long it took. Never logs the password."""
    start = time.perf_counter()
    engine = engine_for("mysql", config)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
    except SQLAlchemyError as exc:
        message = str(getattr(exc, "orig", exc)).splitlines()[0][:300]
        return False, f"Could not connect to MySQL: {message}", None, []
    finally:
        engine.dispose()
    latency_ms = (time.perf_counter() - start) * 1000.0
    return True, f"Connected to MySQL {version}.", latency_ms, []
