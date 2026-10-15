"""Summaries by time window, as events arrive (D1, roadmap Phase 20, L4).

Pure: no database, no clock. `process` takes the saved state, a batch of
events in arrival order and the window, and returns the new state and the
result rows that changed. The caller saves both in one transaction, which is
what makes a repeated batch harmless: the state it starts from is the one
saved with the results of the batch before.

**Windows** (times are whole milliseconds, so window edges never drift):

- *tumbling*: fixed and back to back, `[k*size, (k+1)*size)`;
- *hopping*: fixed size, a new one every `advance`, so they overlap;
- *sliding*: the last `size` at every moment its content changes, which is
  when an event enters (at its time) or leaves (`size` after it), the way
  Azure Stream Analytics defines it; a window `(p - size, p]` is reported for
  each such moment `p` that has an event in it;
- *session*: activity separated by at least `gap`; a session runs from its
  first event to `gap` after its last.

**Time and lateness.** The watermark is the latest event time seen minus the
allowed lateness, and it only moves forward, between batches. A window is
final once the watermark reaches its end. An event that only belongs to
final windows is late: it is dropped and counted, or, with `restate`, added
to windows that closed within `restate_for`, which are reported again with
`restated` counted.

**Measures**: count (of events), sum, average, lowest, highest, first and last
(by event time) of a column. Sum and average skip values that are not
numbers; lowest and highest are over the numbers when a column has any, and
over its text only when it has none.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["tumbling", "hopping", "sliding", "session"]
OPS = ("count", "sum", "average", "lowest", "highest", "first", "last")
NEG_INF = -(2**62)


@dataclass(frozen=True)
class WindowSpec:
    kind: Kind
    size_ms: int = 0
    advance_ms: int = 0
    gap_ms: int = 0
    lateness_ms: int = 0
    late_policy: Literal["drop", "restate"] = "drop"
    restate_for_ms: int = 0

    def check(self) -> None:
        if self.kind in ("tumbling", "hopping", "sliding") and self.size_ms <= 0:
            raise ValueError("A window needs a size.")
        if self.kind == "hopping" and not 0 < self.advance_ms <= self.size_ms:
            raise ValueError("A hopping window moves on by more than nothing and no more than its size.")
        if self.kind == "session" and self.gap_ms <= 0:
            raise ValueError("A session window needs a gap.")
        if self.lateness_ms < 0 or self.restate_for_ms < 0:
            raise ValueError("Lateness cannot be negative.")


@dataclass(frozen=True)
class Measure:
    name: str
    op: str
    column: str | None = None


@dataclass
class Event:
    time_ms: int
    group: tuple[Any, ...]
    values: dict[str, Any]
    seq: int = 0


@dataclass
class Row:
    """One window's measures for one group, as it now stands."""

    start_ms: int
    end_ms: int
    group: tuple[Any, ...]
    values: dict[str, Any]
    events: int
    final: bool
    #: Late events that changed this window after it was final, in this batch.
    restated: int = 0

    @property
    def group_key(self) -> str:
        return group_key(self.group)


@dataclass
class Outcome:
    state: dict[str, Any]
    rows: list[Row] = field(default_factory=list)
    #: Rows reported before that no longer exist: a session that grew or merged.
    removed: list[tuple[int, int, str]] = field(default_factory=list)
    late_dropped: int = 0
    late_restated: int = 0
    closed: int = 0


def group_key(group: tuple[Any, ...] | list[Any]) -> str:
    return hashlib.sha1(json.dumps(list(group), default=str, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------- partials


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    try:
        return float(str(value))
    except ValueError:
        return None


def _empty() -> dict[str, Any]:
    # lo/hi hold numbers, tlo/thi text: a column's numbers win over its text.
    return {"n": 0, "c": {}, "s": {}, "lo": {}, "hi": {}, "tlo": {}, "thi": {}, "f": {}, "l": {}}


def _low(table: dict[str, Any], column: str, value: Any) -> None:
    if column not in table or value < table[column]:
        table[column] = value


def _high(table: dict[str, Any], column: str, value: Any) -> None:
    if column not in table or value > table[column]:
        table[column] = value


def _columns(measures: tuple[Measure, ...]) -> list[str]:
    """Each column once, however many measures read it."""
    return list(dict.fromkeys(m.column for m in measures if m.column))


def _add(partial: dict[str, Any], event: Event, measures: tuple[Measure, ...]) -> None:
    partial["n"] += 1
    for column in _columns(measures):
        value = event.values.get(column)
        if value is None:
            continue
        number = _number(value)
        if number is not None:
            partial["c"][column] = partial["c"].get(column, 0) + 1
            partial["s"][column] = partial["s"].get(column, 0.0) + number
            _low(partial["lo"], column, number)
            _high(partial["hi"], column, number)
        else:
            _low(partial["tlo"], column, str(value))
            _high(partial["thi"], column, str(value))
        stamp = [event.time_ms, event.seq]
        first = partial["f"].get(column)
        if first is None or stamp < first[:2]:
            partial["f"][column] = [*stamp, value]
        last = partial["l"].get(column)
        if last is None or stamp >= last[:2]:
            partial["l"][column] = [*stamp, value]


def _merge(into: dict[str, Any], other: dict[str, Any]) -> None:
    into["n"] += other["n"]
    for column, count in other["c"].items():
        into["c"][column] = into["c"].get(column, 0) + count
    for column, total in other["s"].items():
        into["s"][column] = into["s"].get(column, 0.0) + total
    for name, pick in (("lo", _low), ("tlo", _low), ("hi", _high), ("thi", _high)):
        for column, value in other.get(name, {}).items():
            pick(into.setdefault(name, {}), column, value)
    for column, first in other["f"].items():
        mine = into["f"].get(column)
        if mine is None or first[:2] < mine[:2]:
            into["f"][column] = first
    for column, last in other["l"].items():
        mine = into["l"].get(column)
        if mine is None or last[:2] >= mine[:2]:
            into["l"][column] = last


def finish(partial: dict[str, Any], measures: tuple[Measure, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for measure in measures:
        column = measure.column
        if measure.op == "count":
            out[measure.name] = partial["n"]
        elif measure.op == "sum":
            out[measure.name] = partial["s"].get(column) if column in partial["c"] else None
        elif measure.op == "average":
            count = partial["c"].get(column)
            out[measure.name] = partial["s"][column] / count if count else None
        elif measure.op == "lowest":
            out[measure.name] = partial["lo"][column] if column in partial["lo"] else partial.get("tlo", {}).get(column)
        elif measure.op == "highest":
            out[measure.name] = partial["hi"][column] if column in partial["hi"] else partial.get("thi", {}).get(column)
        elif measure.op == "first":
            found = partial["f"].get(column)
            out[measure.name] = found[2] if found else None
        elif measure.op == "last":
            found = partial["l"].get(column)
            out[measure.name] = found[2] if found else None
    return out


def _of(events: list[Event], measures: tuple[Measure, ...]) -> dict[str, Any]:
    partial = _empty()
    for event in events:
        _add(partial, event, measures)
    return partial


# ---------------------------------------------------------------- engine


def process(state: dict[str, Any] | None, events: list[Event], spec: WindowSpec,
            measures: tuple[Measure, ...]) -> Outcome:
    spec.check()
    state = json.loads(json.dumps(state or {}))  # never change the caller's copy
    watermark = state.get("wm")
    old_wm = NEG_INF if watermark is None else int(watermark)
    batch_max = max((e.time_ms for e in events), default=None)
    seen_max = state.get("max_t")
    if batch_max is not None:
        seen_max = batch_max if seen_max is None else max(int(seen_max), batch_max)
    state["max_t"] = seen_max
    new_wm = old_wm if seen_max is None else max(old_wm, int(seen_max) - spec.lateness_ms)
    state["wm"] = None if new_wm == NEG_INF else new_wm
    if spec.kind in ("tumbling", "hopping"):
        return _fixed(state, events, spec, measures, old_wm, new_wm)
    if spec.kind == "session":
        return _sessions(state, events, spec, measures, old_wm, new_wm)
    return _sliding(state, events, spec, measures, old_wm, new_wm)


def _starts(time_ms: int, spec: WindowSpec) -> list[int]:
    if spec.kind == "tumbling":
        return [(time_ms // spec.size_ms) * spec.size_ms]
    first = (time_ms - spec.size_ms) // spec.advance_ms + 1
    last = time_ms // spec.advance_ms
    return [k * spec.advance_ms for k in range(first, last + 1)]


def _restatable(end_ms: int, old_wm: int, spec: WindowSpec) -> bool:
    return spec.late_policy == "restate" and old_wm - end_ms <= spec.restate_for_ms


def _fixed(state, events, spec, measures, old_wm, new_wm) -> Outcome:
    windows: dict[str, dict[str, Any]] = state.setdefault("windows", {})
    outcome = Outcome(state=state)
    touched: set[str] = set()
    restated: dict[str, int] = {}
    for event in events:
        entered = changed_final = False
        gkey = group_key(event.group)
        for start in _starts(event.time_ms, spec):
            end = start + spec.size_ms
            key = f"{start}|{end}|{gkey}"
            window = windows.get(key)
            if end <= old_wm:
                if not _restatable(end, old_wm, spec):
                    continue
                if window is None:
                    window = windows[key] = {"s": start, "e": end, "g": list(event.group), "p": _empty(), "closed": True}
                restated[key] = restated.get(key, 0) + 1
                changed_final = True
            elif window is None:
                window = windows[key] = {"s": start, "e": end, "g": list(event.group), "p": _empty(), "closed": False}
            _add(window["p"], event, measures)
            entered = True
            touched.add(key)
        if not entered:
            outcome.late_dropped += 1
        elif changed_final:
            outcome.late_restated += 1
    for key, window in windows.items():
        if not window["closed"] and window["e"] <= new_wm:
            window["closed"] = True
            outcome.closed += 1
            touched.add(key)
    for key in sorted(touched, key=lambda k: (windows[k]["s"], windows[k]["e"], k)):
        window = windows[key]
        outcome.rows.append(Row(window["s"], window["e"], tuple(window["g"]), finish(window["p"], measures),
                                window["p"]["n"], window["closed"], restated.get(key, 0)))
    keep = spec.restate_for_ms if spec.late_policy == "restate" else -1
    for key in [k for k, w in windows.items() if w["closed"] and new_wm - w["e"] > keep]:
        del windows[key]
    return outcome


def _sessions(state, events, spec, measures, old_wm, new_wm) -> Outcome:
    groups: dict[str, list[dict[str, Any]]] = state.setdefault("sessions", {})
    outcome = Outcome(state=state)
    gap = spec.gap_ms
    touched: dict[str, dict[str, Any]] = {}
    for event in events:
        gkey = group_key(event.group)
        sessions = groups.setdefault(gkey, [])
        t = event.time_ms
        near = [s for s in sessions if s["s"] - gap < t < s["e"] + gap]
        closed = [s for s in near if s["closed"]]
        late = bool(closed) or (not near and t + gap <= old_wm)
        if late:
            ends = [s["e"] + gap for s in closed] or [t + gap]
            if not all(_restatable(end, old_wm, spec) for end in ends):
                outcome.late_dropped += 1
                continue
        merged = {
            "id": min([s["id"] for s in near], default=f"{t}:{event.seq}"),
            "s": min([t, *[s["s"] for s in near]]), "e": max([t, *[s["e"] for s in near]]),
            "g": list(event.group), "p": _empty(), "closed": False,
            "restated": sum(s.get("restated", 0) for s in near),
            # Every row reported for the sessions this one absorbs, to remove when it is reported.
            "stale": [k for s in near for k in ([s["shown"]] if s.get("shown") else []) + s.get("stale", [])],
        }
        for s in near:
            _merge(merged["p"], s["p"])
            sessions.remove(s)
            touched.pop(s["id"], None)
        _add(merged["p"], event, measures)
        if late:
            merged["restated"] += 1
            merged["closed"] = merged["e"] + gap <= old_wm
            outcome.late_restated += 1
        sessions.append(merged)
        sessions.sort(key=lambda s: s["s"])
        touched[merged["id"]] = merged
    for sessions in groups.values():
        for session in sessions:
            if not session["closed"] and session["e"] + gap <= new_wm:
                session["closed"] = True
                outcome.closed += 1
                touched[session["id"]] = session
    for gkey, sessions in groups.items():
        for session in sessions:
            if session["id"] not in touched:
                continue
            current = [session["s"], session["e"] + gap]
            for stale in session.get("stale", []):
                if stale != current:
                    outcome.removed.append((stale[0], stale[1], gkey))
            outcome.rows.append(Row(current[0], current[1], tuple(session["g"]), finish(session["p"], measures),
                                    session["p"]["n"], session["closed"], session.pop("restated", 0)))
            session["restated"] = 0
            session["shown"] = current
            session["stale"] = []
    outcome.rows.sort(key=lambda r: (r.start_ms, r.group_key))
    keep = spec.restate_for_ms if spec.late_policy == "restate" else -1
    for gkey in list(groups):
        groups[gkey] = [s for s in groups[gkey] if not (s["closed"] and new_wm - (s["e"] + gap) > keep)]
        if not groups[gkey]:
            del groups[gkey]
    return outcome


def _sliding(state, events, spec, measures, old_wm, new_wm) -> Outcome:
    """Moments are whole milliseconds: an event at `t` is in the windows that end
    at `t` up to `t + size - 1`, and leaves the window that ends at `t + size`."""
    buffers: dict[str, dict[str, Any]] = state.setdefault("buffers", {})
    outcome = Outcome(state=state)
    size = spec.size_ms
    late_ranges: dict[str, list[tuple[int, int]]] = {}
    for event in events:
        t = event.time_ms
        gkey = group_key(event.group)
        if t + size - 1 <= old_wm and not _restatable(t + size - 1, old_wm, spec):
            outcome.late_dropped += 1  # every window it belongs to is final, and too long ago
            continue
        buffer = buffers.setdefault(gkey, {"g": list(event.group), "events": []})
        buffer["events"].append([t, event.seq, event.values])
        if t <= old_wm and spec.late_policy == "restate":
            late_ranges.setdefault(gkey, []).append((t, min(old_wm, t + size - 1)))
    restated_events = 0
    for gkey, buffer in buffers.items():
        held = sorted(buffer["events"], key=lambda e: (e[0], e[1]))
        stream = [Event(e[0], tuple(buffer["g"]), e[2], e[1]) for e in held]
        moments = sorted({e.time_ms for e in stream} | {e.time_ms + size for e in stream})
        ranges = late_ranges.get(gkey, [])
        restated = {p for p in moments for low, high in ranges if low <= p <= high and _restatable(p, old_wm, spec)}
        restated_events += sum(1 for low, high in ranges
                               if any(low <= p <= high and _restatable(p, old_wm, spec) for p in moments))
        for p in moments:
            if p <= old_wm and p not in restated:
                continue  # final, reported before, and unchanged
            inside = [e for e in stream if p - size < e.time_ms <= p]
            if not inside:
                continue
            final = p <= new_wm
            if final and p > old_wm:
                outcome.closed += 1
            outcome.rows.append(Row(p - size, p, tuple(buffer["g"]), finish(_of(inside, measures), measures),
                                    len(inside), final, 1 if p in restated else 0))
        keep = spec.restate_for_ms if spec.late_policy == "restate" else 0
        buffer["events"] = [e for e in buffer["events"] if e[0] + size > new_wm - keep]
    outcome.late_restated = restated_events
    for gkey in [k for k, b in buffers.items() if not b["events"]]:
        del buffers[gkey]
    outcome.rows.sort(key=lambda r: (r.end_ms, r.group_key))
    return outcome
