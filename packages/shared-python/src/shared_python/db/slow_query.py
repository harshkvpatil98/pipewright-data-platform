"""Log the queries that are actually slow, when you ask it to.

Turning on SQLAlchemy's `echo` logs *every* statement, which is unreadable in
production and a performance drag in itself. This logs only the statements that
cross a threshold you set -- the ones worth seeing when a page is slow -- and
stays completely off (zero overhead beyond an if-check) until enabled. Each
line carries the request's correlation id through the standard logger, so a slow
query is traceable back to the request that ran it.
"""

from __future__ import annotations

import time

from sqlalchemy import event
from sqlalchemy.engine import Engine

from shared_python.logging import get_logger

_STACK_KEY = "_pw_slow_query_start"


def install_slow_query_logger(engine: Engine, *, threshold_ms: float, logger=None) -> None:
    """Log any statement on `engine` that runs for at least `threshold_ms`.

    A threshold of zero or less is a no-op, so the caller can pass the config
    value straight through without guarding it. Registered once per engine.
    """
    if threshold_ms <= 0:
        return
    log = logger or get_logger("shared_python.db.slow_query")

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, _cursor, _statement, _params, _context, _executemany):  # noqa: ANN001
        # A stack, not a single slot: a statement can trigger a nested execute,
        # and each must time against its own start.
        conn.info.setdefault(_STACK_KEY, []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, _cursor, statement, _params, _context, _executemany):  # noqa: ANN001
        stack = conn.info.get(_STACK_KEY)
        if not stack:
            return
        elapsed_ms = (time.perf_counter() - stack.pop()) * 1000.0
        if elapsed_ms >= threshold_ms:
            # Truncate the statement: a slow query is often a huge IN-list, and
            # the log line is a signpost, not the full payload.
            log.warning(
                "slow_query duration_ms=%.1f threshold_ms=%s statement=%s",
                elapsed_ms,
                threshold_ms,
                " ".join(statement.split())[:500],
            )
