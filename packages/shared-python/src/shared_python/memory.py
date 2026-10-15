"""How much memory one run's data may take, and how much it is taking (D2, O8).

A run's data lives in memory as frames. Without a ceiling, one recipe that
joins on a repeated key, or reads a table far larger than expected, takes the
worker's memory and the worker with it, along with every other run on it.
`RUN_MEMORY_LIMIT_MB` (default 2,048) is that ceiling: the executor checks the
data after every step (`check_frame`), a join counts its exact output before
building it, and on Linux the worker caps its address space as a backstop
(`cap_address_space`), so an allocation past it fails one run, not the worker.

`frame_bytes` is an estimate that errs high: numbers by their exact size,
text by a sample of its values.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

from shared_python.errors import BadRequestError

DEFAULT_RUN_MEMORY_LIMIT_MB = 2048
#: The least a ceiling may be: below it, ordinary previews would stop.
SMALLEST_LIMIT_MB = 128
#: Room the worker needs beyond one run's data: the interpreter and its
#: libraries reserve about 1.3 GB of address space, and each thread more.
WORKER_HEADROOM_MB = 2048
#: Values of a text column looked at to estimate its size.
_SAMPLE = 1_000
_MB = 1024 * 1024


#: What a run that ran out of memory says (the worker's cap turned an allocation into MemoryError).
OUT_OF_MEMORY = (
    "This needed more memory than a run may take here (RUN_MEMORY_LIMIT_MB) and stopped. Filter or group "
    "the data earlier, or ask an admin to raise the ceiling."
)


def run_memory_limit_mb() -> int:
    raw = os.environ.get("RUN_MEMORY_LIMIT_MB", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_RUN_MEMORY_LIMIT_MB
    except ValueError:
        value = DEFAULT_RUN_MEMORY_LIMIT_MB
    return max(SMALLEST_LIMIT_MB, value)


def run_memory_limit_bytes() -> int:
    return run_memory_limit_mb() * _MB


def frame_bytes(frame: pd.DataFrame) -> int:
    """About how many bytes a frame holds."""
    total = int(frame.index.memory_usage(deep=False))
    for name in frame.columns:
        series = frame[name]
        if series.dtype == object or pd.api.types.is_string_dtype(series.dtype):
            count = len(series)
            if not count:
                continue
            sample = series.iloc[:: max(1, count // _SAMPLE)].head(_SAMPLE)
            each = sum(sys.getsizeof(value) for value in sample) / max(len(sample), 1)
            total += int(count * (each + 8))  # the value, and the pointer to it
        else:
            total += int(series.memory_usage(index=False, deep=False))
    return total


def megabytes(size: float) -> str:
    """A size in words; below 10 MB to one decimal place, so "2.1 MB" is never written "2 MB"
    beside a ceiling of 2 MB."""
    value = size / _MB
    if value < 10:
        return f"{max(value, 0.1):.1f} MB"
    return f"{round(value):,} MB"


class RunMemoryExceeded(BadRequestError):
    """A run's data would take more than RUN_MEMORY_LIMIT_MB."""


def check_frame(frame: pd.DataFrame, *, where: str) -> None:
    """Stop the run when its data has grown past the ceiling, saying where and how big."""
    size = frame_bytes(frame)
    limit = run_memory_limit_bytes()
    if size > limit:
        raise RunMemoryExceeded(
            f"{where} made the data {megabytes(size)}, past this run's ceiling of {megabytes(limit)} "
            "(RUN_MEMORY_LIMIT_MB). Filter or group the data before that step, or ask an admin to raise the ceiling."
        )


def cap_address_space(*, headroom_mb: int = WORKER_HEADROOM_MB) -> int | None:
    """On Linux, limit this process's address space so an allocation past it
    raises MemoryError in the run that made it, instead of the kernel killing
    the worker. The cap is twice one run's ceiling (a step briefly holds its
    input and its output) plus room for the worker itself.

    Returns the cap in bytes, or None where address-space limits are not
    available or not reliable (macOS), or when WORKER_ADDRESS_SPACE_CAP=false
    turns it off (for a library that reserves far more than it uses).
    """
    if not sys.platform.startswith("linux"):
        return None
    if os.environ.get("WORKER_ADDRESS_SPACE_CAP", "").strip().lower() in ("0", "false", "no", "off"):
        return None
    import resource

    cap = (2 * run_memory_limit_mb() + headroom_mb) * _MB
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        cap = min(cap, hard)
    if soft != resource.RLIM_INFINITY and soft <= cap:
        return soft
    resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
    return cap
