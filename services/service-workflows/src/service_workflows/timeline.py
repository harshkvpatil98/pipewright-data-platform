"""Where a run's time actually went.

A run detail page lists nodes and their durations, which answers "how long did
each step take" but not "why did this run take eleven minutes". A timeline does,
because the answer is almost always one step, and seeing it as a bar next to
nine short ones takes no reading at all.

The executor runs nodes one at a time, so this is a waterfall rather than a
true Gantt. That is worth stating plainly instead of drawing overlapping bars
that suggest a parallelism the engine does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class TimelineEntry:
    node_key: str
    node_name: str
    node_type: str
    status: str
    # Milliseconds from the start of the run, so bars can be positioned.
    offset_ms: int
    duration_ms: int
    share_percentage: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "status": self.status,
            "offset_ms": self.offset_ms,
            "duration_ms": self.duration_ms,
            "share_percentage": self.share_percentage,
        }


@dataclass
class Timeline:
    total_ms: int
    entries: list[TimelineEntry]
    slowest_node_key: str | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_ms": self.total_ms,
            "entries": [entry.to_dict() for entry in self.entries],
            "slowest_node_key": self.slowest_node_key,
            "summary": self.summary,
        }


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _humanise(milliseconds: int) -> str:
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    return f"{minutes:.1f} min"


def build_timeline(
    *,
    run_started_at: datetime | None,
    run_finished_at: datetime | None,
    node_runs: list[dict[str, Any]],
) -> Timeline:
    """Lay a run's nodes out against the wall clock.

    Skipped nodes are kept with a zero-width bar rather than dropped: a gap in
    the sequence is exactly the thing worth noticing.
    """
    start = _as_utc(run_started_at)
    finish = _as_utc(run_finished_at)

    total_ms = 0
    if start is not None and finish is not None:
        total_ms = max(int((finish - start).total_seconds() * 1000), 0)

    entries: list[TimelineEntry] = []
    running_offset = 0

    for node in sorted(node_runs, key=lambda item: item.get("sequence") or 0):
        duration = int(node.get("duration_ms") or 0)
        node_started = _as_utc(node.get("started_at"))

        if start is not None and node_started is not None:
            offset = max(int((node_started - start).total_seconds() * 1000), 0)
        else:
            # A skipped node never started; place it where it would have run.
            offset = running_offset

        entries.append(
            TimelineEntry(
                node_key=str(node.get("node_key") or ""),
                node_name=str(node.get("node_name") or node.get("node_key") or ""),
                node_type=str(node.get("node_type") or "unknown"),
                status=str(node.get("status") or "pending"),
                offset_ms=offset,
                duration_ms=duration,
                share_percentage=round(duration / total_ms * 100, 1) if total_ms else 0.0,
            )
        )
        running_offset = offset + duration

    if total_ms == 0 and entries:
        # A run still in flight has no finish time; fall back to what has run.
        total_ms = max(entry.offset_ms + entry.duration_ms for entry in entries)
        for entry in entries:
            entry.share_percentage = (
                round(entry.duration_ms / total_ms * 100, 1) if total_ms else 0.0
            )

    timed = [entry for entry in entries if entry.duration_ms > 0]
    slowest = max(timed, key=lambda entry: entry.duration_ms) if timed else None

    if not entries:
        summary = "This run recorded no nodes."
    elif slowest is None:
        summary = "Every node finished too quickly to measure."
    elif slowest.share_percentage >= 50:
        summary = (
            f"'{slowest.node_name}' took {_humanise(slowest.duration_ms)}, "
            f"{slowest.share_percentage:.0f}% of the whole run."
        )
    else:
        summary = (
            f"{_humanise(total_ms)} across {len(entries)} node(s); "
            f"the slowest was '{slowest.node_name}' at {_humanise(slowest.duration_ms)}."
        )

    return Timeline(
        total_ms=total_ms,
        entries=entries,
        slowest_node_key=slowest.node_key if slowest else None,
        summary=summary,
    )
