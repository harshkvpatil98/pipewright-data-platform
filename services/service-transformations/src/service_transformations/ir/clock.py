"""The evaluation instant: the one clock every clock-dependent function reads.

`now()`, `today()` and `age_years()` depend on when they run. Left to the wall
clock, a replay six months later returns a different answer from the same
pinned inputs and the same recipe, and there is no way to tell a real change
from the calendar moving (phase-18 §3). So a run freezes one instant at its
start, records it in the run's execution context, and evaluates every
clock-dependent function against it; a replay installs the *recorded* instant
instead of the current one.

Outside any run -- a Studio preview, a unit test -- nothing is frozen and the
functions read the real clock through the same door, so there is exactly one
place that knows what "now" is.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Iterator

_INSTANT: ContextVar[datetime | None] = ContextVar("pipewright_evaluation_instant", default=None)


def evaluation_instant() -> datetime:
    """The frozen instant when one is installed, else the real clock. Always
    timezone-aware UTC."""
    frozen = _INSTANT.get()
    if frozen is not None:
        return frozen
    return datetime.now(UTC)


def is_frozen() -> bool:
    return _INSTANT.get() is not None


@contextmanager
def frozen_clock(instant: datetime) -> Iterator[datetime]:
    """Install `instant` as the evaluation instant for the duration of the block.

    A naive datetime is taken as UTC -- the only zone a run records -- rather
    than guessed at from the host.
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    else:
        instant = instant.astimezone(UTC)
    token = _INSTANT.set(instant)
    try:
        yield instant
    finally:
        _INSTANT.reset(token)
