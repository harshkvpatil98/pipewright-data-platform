"""Keeping a claimed run's lease while its work goes on (adoption-readiness A7).

A worker claims a run with a lease, and another worker fails the run as
stalled once the lease has run out: that is how a run whose worker died gets
noticed. A long run, though, outlives any fixed lease, and was failed as
stalled by a second worker while it was still working. While the work runs,
`kept` renews the lease from a side thread on its own connection. If the
process dies, the thread dies with it, the lease runs out and the run is
failed, as it should be.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Table, update

from shared_python.logging import get_logger

logger = get_logger(__name__)


def renew(engine: Any, *, table: Table, row_id: uuid.UUID, owner: str, lease_seconds: int) -> bool:
    """Extend the lease if this owner still holds it. Returns whether it did."""
    with engine.begin() as connection:
        result = connection.execute(
            update(table)
            .where(
                table.c.id == row_id,
                table.c.claim_owner_id == owner,
                table.c.claim_expires_at.is_not(None),
            )
            .values(claim_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds))
        )
    return bool(result.rowcount)


@contextmanager
def kept(
    engine: Any,
    *,
    table: Table,
    row_id: uuid.UUID,
    owner: str | None,
    lease_seconds: int,
    every_seconds: float | None = None,
) -> Iterator[None]:
    """Renew the lease on `row_id` every so often until the block ends."""
    if not owner:
        yield
        return
    stop = threading.Event()
    interval = every_seconds or max(5.0, lease_seconds / 4)

    def keep() -> None:
        while not stop.wait(interval):
            try:
                if not renew(engine, table=table, row_id=row_id, owner=owner, lease_seconds=lease_seconds):
                    return  # finished, or no longer ours: nothing left to keep
            except Exception:  # noqa: BLE001 - a missed renewal is retried next time
                logger.warning("lease_renewal_failed table=%s row_id=%s", table.name, row_id, exc_info=True)

    thread = threading.Thread(target=keep, name=f"lease-{row_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
