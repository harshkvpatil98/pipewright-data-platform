"""Keeping what a recipe's first steps made, so changing a later one is quick (D2, O6).

Editing step 14 of 15 used to read the dataset again and run all 15 steps.
Each step's output is now kept, addressed by everything that decides it:

- the input: the dataset, and the content hash of the version read (an
  erasure rewrites a file and its hash with it, so a kept result of erased
  rows can never be found again);
- the reader's policies on it: who may see which rows and columns;
- every step up to that one, exactly as configured;
- for a join or union, the other dataset's version and the reader's
  policies on it.

A run reuses what a preview kept, and the reverse, when all of that agrees.
A step that reads the clock (`now()`, `today()`, a run's frozen instant) is
never kept, nor anything after it; nor is the work of a step with nothing
to address it by. Kept results live in this process's memory, bounded
(`RECIPE_CACHE_MB`, default 512, least recently used first out) and for at
most `RECIPE_CACHE_MINUTES` (30).

Frames are shared, not copied: a kept frame is handed to the next step,
which (every step does) copies before it writes. `tests/test_prefix_cache.py`
holds every step type to that.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_python.memory import check_frame, frame_bytes


def _setting(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


@dataclass
class Kept:
    frame: pd.DataFrame
    #: What each step so far did (`executor.StepOutcome`), and the warnings they gave.
    outcomes: list[Any]
    warnings: list[str]
    size: int
    #: What the caller wanted to know about the input (`describe`), kept with every
    #: step's result so it is there even after the input itself has gone.
    source: Any = None
    at: float = field(default_factory=time.monotonic)


class PrefixCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[str, Kept] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    @property
    def budget(self) -> int:
        return _setting("RECIPE_CACHE_MB", 512) * 1024 * 1024

    @property
    def lifetime(self) -> float:
        return _setting("RECIPE_CACHE_MINUTES", 30) * 60.0

    def get(self, key: str) -> Kept | None:
        with self._lock:
            kept = self._entries.get(key)
            if kept is None:
                return None
            if time.monotonic() - kept.at > self.lifetime:
                self._drop(key)
                return None
            self._entries.move_to_end(key)
            return kept

    def put(self, key: str, kept: Kept) -> None:
        budget = self.budget
        # One result larger than half the store would push out everything else.
        if kept.size > budget // 2:
            return
        with self._lock:
            if key in self._entries:
                self._drop(key)
            self._entries[key] = kept
            self._bytes += kept.size
            while self._bytes > budget and self._entries:
                self._drop(next(iter(self._entries)))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def __len__(self) -> int:
        return len(self._entries)

    def _drop(self, key: str) -> None:
        kept = self._entries.pop(key)
        self._bytes -= kept.size


CACHE = PrefixCache()


def _digest(*parts: Any) -> str:
    text = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def step_keys(base: str, steps: list[Any], other_of: Callable[[str, dict[str, Any]], str | None] | None) -> list[str | None]:
    """The address of the result after each step; None from the first step that has none."""
    keys: list[str | None] = []
    previous: str | None = base
    for step in steps:
        if previous is None:
            keys.append(None)
            continue
        config = dict(step.config or {})
        extra = ""
        if step.step_type in ("join_datasets", "union_datasets"):
            extra = other_of(step.step_type, config) if other_of is not None else None
            if extra is None:
                previous = None
                keys.append(None)
                continue
        previous = _digest(previous, step.step_type, config, extra)
        keys.append(previous)
    return keys


@dataclass
class Ran:
    frame: pd.DataFrame
    warnings: list[str]
    outcomes: list[Any]
    #: How many steps' work was taken from what was kept, rather than done again.
    reused_steps: int
    #: Whether the input itself was taken from what was kept.
    reused_input: bool
    #: `describe(input)`.
    source: Any = None


def run_steps(
    *,
    base: str | None,
    load: Callable[[], pd.DataFrame],
    steps: list[Any],
    apply: Callable[[pd.DataFrame, Any], tuple[pd.DataFrame, list[str]]],
    other_of: Callable[[str, dict[str, Any]], str | None] | None = None,
    before_step: Callable[[int, Any], None] | None = None,
    describe: Callable[[pd.DataFrame], Any] | None = None,
    accept: Callable[[Any], None] | None = None,
) -> Ran:
    """Run `steps` over the input `load` reads, from the furthest result already kept.

    `base` addresses the input (None: keep nothing); `apply` does one step;
    `before_step(index, step)` is told before each step that is actually run;
    `describe(input)` is worked out once and handed back, reused or not, and
    `accept(described)` may refuse the input before any step runs, whether it
    was read now or kept from before.
    """
    from service_transformations.executor import StepOutcome
    from service_transformations.ir.clock import watching_reads

    keys = step_keys(base, steps, other_of) if base is not None else [None] * len(steps)
    start, frame, outcomes, warnings, source = 0, None, [], [], None
    reused_input = False
    for index in range(len(steps), 0, -1):
        key = keys[index - 1]
        kept = CACHE.get(key) if key is not None else None
        if kept is not None:
            start, frame, outcomes, warnings = index, kept.frame, list(kept.outcomes), list(kept.warnings)
            source, reused_input = kept.source, True
            break
    if frame is None:
        kept = CACHE.get(base) if base is not None else None
        if kept is not None:
            frame, source, reused_input = kept.frame, kept.source, True
        else:
            frame = load()
            source = describe(frame) if describe is not None else None
            if base is not None:
                CACHE.put(base, Kept(frame=frame, outcomes=[], warnings=[], size=frame_bytes(frame), source=source))

    if accept is not None:
        accept(source)

    keeping = True
    for index in range(start, len(steps)):
        step = steps[index]
        if before_step is not None:
            before_step(index, step)
        rows_before, columns_before = int(len(frame)), int(len(frame.columns))
        with watching_reads() as reads:
            frame, step_warnings = apply(frame, step)
        check_frame(frame, where=f"Step {index + 1} ({step.step_type.replace('_', ' ')})")
        warnings.extend(step_warnings)
        outcomes.append(StepOutcome(index=index, step_type=step.step_type, rows_before=rows_before,
                                    rows_after=int(len(frame)), columns_before=columns_before,
                                    columns_after=int(len(frame.columns))))
        # What the clock decided is not the same next time; nor is anything built on it.
        keeping = keeping and not reads and keys[index] is not None
        if keeping:
            CACHE.put(keys[index], Kept(frame=frame, outcomes=list(outcomes), warnings=list(warnings),
                                        size=frame_bytes(frame), source=source))
    return Ran(frame=frame, warnings=warnings, outcomes=outcomes, reused_steps=start, reused_input=reused_input,
               source=source)
