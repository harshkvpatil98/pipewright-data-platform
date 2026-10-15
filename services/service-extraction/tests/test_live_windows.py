"""Summaries by time window (D1, L4): the engine against a brute-force reference.

Every window kind is checked the same way: random events, fed in random
batches, must give exactly the windows a direct computation over all the
events gives. Then lateness: events out of order within the allowed lateness
change nothing; later ones are dropped and counted, or restate a window that
closed recently. And a batch repeated from the saved state gives the same
answer, which is what makes a crash mid-batch harmless.
"""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from service_extraction.live.windows import Event, Measure, WindowSpec, finish, group_key, process, _of

MEASURES = (
    Measure("events", "count"),
    Measure("total", "sum", "amount"),
    Measure("mean", "average", "amount"),
    Measure("low", "lowest", "amount"),
    Measure("high", "highest", "amount"),
    Measure("opened", "first", "label"),
    Measure("closed_with", "last", "label"),
)


def _events(seed: int, count: int = 120, span: int = 60_000) -> list[Event]:
    rng = random.Random(seed)
    out = []
    for seq in range(count):
        out.append(Event(
            time_ms=rng.randrange(0, span),
            group=(rng.choice(["north", "south"]),),
            values={"amount": rng.choice([rng.randint(1, 50), None, rng.random() * 10]), "label": f"e{seq}"},
            seq=seq,
        ))
    out.sort(key=lambda e: (e.time_ms, e.seq))
    for index, event in enumerate(out):
        event.seq = index  # arrival order is time order here
    return out


def _reference(events: list[Event], spec: WindowSpec) -> dict[tuple[int, int, str], dict[str, Any]]:
    """Each window computed directly from every event, no state, no batches."""
    out: dict[tuple[int, int, str], dict[str, Any]] = {}
    groups = sorted({e.group for e in events})
    for group in groups:
        mine = [e for e in events if e.group == group]
        windows: set[tuple[int, int]] = set()
        if spec.kind == "tumbling":
            windows = {((e.time_ms // spec.size_ms) * spec.size_ms, (e.time_ms // spec.size_ms) * spec.size_ms + spec.size_ms) for e in mine}
        elif spec.kind == "hopping":
            for e in mine:
                start = (e.time_ms // spec.advance_ms) * spec.advance_ms
                while start > e.time_ms - spec.size_ms:
                    windows.add((start, start + spec.size_ms))
                    start -= spec.advance_ms
        elif spec.kind == "sliding":
            for p in {e.time_ms for e in mine} | {e.time_ms + spec.size_ms for e in mine}:
                if any(p - spec.size_ms < e.time_ms <= p for e in mine):
                    windows.add((p - spec.size_ms, p))
        else:
            ordered = sorted(mine, key=lambda e: (e.time_ms, e.seq))
            start = last = None
            for e in ordered:
                if start is None:
                    start = last = e.time_ms
                elif e.time_ms - last >= spec.gap_ms:
                    windows.add((start, last + spec.gap_ms))
                    start = last = e.time_ms
                else:
                    last = e.time_ms
            if start is not None:
                windows.add((start, last + spec.gap_ms))
        for start, end in windows:
            if spec.kind == "sliding":
                inside = [e for e in mine if start < e.time_ms <= end]
            elif spec.kind == "session":
                inside = [e for e in mine if start <= e.time_ms < end - spec.gap_ms + 1]
            else:
                inside = [e for e in mine if start <= e.time_ms < end]
            out[(start, end, group_key(group))] = {"values": finish(_of(inside, MEASURES), MEASURES), "events": len(inside)}
    return out


def _run(events: list[Event], spec: WindowSpec, seed: int, *, repeat_each: bool = False):
    """Feed the events in random batches; keep the latest row per window."""
    rng = random.Random(seed)
    state: dict[str, Any] | None = None
    table: dict[tuple[int, int, str], dict[str, Any]] = {}
    counts = {"dropped": 0, "restated": 0}
    index = 0
    while index < len(events):
        size = rng.randint(1, 15)
        batch = events[index:index + size]
        index += size
        outcome = process(state, batch, spec, MEASURES)
        if repeat_each:
            again = process(json.loads(json.dumps(state)) if state else None, batch, spec, MEASURES)
            assert again.rows == outcome.rows and again.state == outcome.state
        state = json.loads(json.dumps(outcome.state))  # what the database would hand back
        for start, end, gkey in outcome.removed:
            table.pop((start, end, gkey), None)
        for row in outcome.rows:
            table[(row.start_ms, row.end_ms, row.group_key)] = {"values": row.values, "events": row.events,
                                                                 "final": row.final}
        counts["dropped"] += outcome.late_dropped
        counts["restated"] += outcome.late_restated
    return table, counts, state


def _same(table, reference) -> None:
    assert set(table) == set(reference)
    for key, expected in reference.items():
        got = table[key]
        assert got["events"] == expected["events"], key
        for name, value in expected["values"].items():
            if isinstance(value, float):
                assert got["values"][name] == pytest.approx(value), (key, name)
            else:
                assert got["values"][name] == value, (key, name)


SPECS = [
    WindowSpec("tumbling", size_ms=10_000),
    WindowSpec("hopping", size_ms=10_000, advance_ms=3_000),
    WindowSpec("sliding", size_ms=7_000),
    WindowSpec("session", gap_ms=4_000),
]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_every_window_kind_matches_a_direct_computation(spec, seed):
    events = _events(seed)
    table, counts, _ = _run(events, spec, seed, repeat_each=True)
    _same(table, _reference(events, spec))
    assert counts == {"dropped": 0, "restated": 0}


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
@pytest.mark.parametrize("seed", [11, 12, 13])
def test_events_out_of_order_within_the_lateness_change_nothing(spec, seed):
    events = _events(seed)
    rng = random.Random(seed)
    lateness = 5_000
    # Each event arrives up to `lateness` after its own time, so none is ever behind the watermark.
    arrivals = sorted(events, key=lambda e: e.time_ms + rng.randrange(0, lateness))
    for index, event in enumerate(arrivals):
        event.seq = index
    late_spec = WindowSpec(spec.kind, spec.size_ms, spec.advance_ms, spec.gap_ms, lateness_ms=lateness)
    table, counts, _ = _run(arrivals, late_spec, seed)
    _same(table, _reference(events, late_spec))
    assert counts == {"dropped": 0, "restated": 0}


def test_windows_become_final_as_the_watermark_passes_them():
    spec = WindowSpec("tumbling", size_ms=10_000, lateness_ms=2_000)
    first = process(None, [Event(1_000, ("a",), {"amount": 1}, 0)], spec, MEASURES)
    assert [r.final for r in first.rows] == [False]
    second = process(first.state, [Event(12_500, ("a",), {"amount": 2}, 1)], spec, MEASURES)
    # Watermark 10,500: the first window (ends 10,000) is final; the second is open.
    assert [(r.start_ms, r.final) for r in second.rows] == [(0, True), (10_000, False)]
    assert second.closed == 1 and second.state["wm"] == 10_500


def test_a_late_event_is_dropped_and_counted():
    spec = WindowSpec("tumbling", size_ms=10_000)
    state = process(None, [Event(25_000, ("a",), {"amount": 1}, 0)], spec, MEASURES).state
    late = process(state, [Event(3_000, ("a",), {"amount": 5}, 1)], spec, MEASURES)
    assert late.late_dropped == 1 and late.rows == []


def test_a_late_event_restates_a_recently_closed_window():
    spec = WindowSpec("tumbling", size_ms=10_000, late_policy="restate", restate_for_ms=20_000)
    one = process(None, [Event(1_000, ("a",), {"amount": 1}, 0)], spec, MEASURES)
    two = process(one.state, [Event(25_000, ("a",), {"amount": 1}, 1)], spec, MEASURES)
    assert [(r.start_ms, r.final) for r in two.rows if r.start_ms == 0] == [(0, True)]
    late = process(two.state, [Event(4_000, ("a",), {"amount": 5}, 2)], spec, MEASURES)
    assert late.late_restated == 1 and late.late_dropped == 0
    (row,) = late.rows
    assert (row.start_ms, row.final, row.restated, row.values["total"], row.events) == (0, True, 1, 6.0, 2)
    # Too long ago: past restate_for, so dropped.
    far = process(late.state, [Event(60_000, ("a",), {}, 3)], spec, MEASURES)
    gone = process(far.state, [Event(2_000, ("a",), {"amount": 9}, 4)], spec, MEASURES)
    assert gone.late_dropped == 1 and gone.rows == []


def test_a_late_event_can_join_a_closed_session_when_restating():
    spec = WindowSpec("session", gap_ms=5_000, late_policy="restate", restate_for_ms=30_000)
    one = process(None, [Event(t, ("a",), {"amount": 1}, i) for i, t in enumerate((1_000, 3_000))], spec, MEASURES)
    two = process(one.state, [Event(20_000, ("a",), {"amount": 1}, 2)], spec, MEASURES)
    assert any(r.start_ms == 1_000 and r.end_ms == 8_000 and r.final for r in two.rows)
    late = process(two.state, [Event(6_000, ("a",), {"amount": 4}, 3)], spec, MEASURES)
    # The late event extends the closed session [1000, 8000) to [1000, 11000); the old row goes.
    assert late.removed == [(1_000, 8_000, group_key(("a",)))]
    (row,) = late.rows
    assert (row.start_ms, row.end_ms, row.final, row.restated, row.events) == (1_000, 11_000, True, 1, 3)


def test_two_sessions_an_event_bridges_become_one():
    spec = WindowSpec("session", gap_ms=5_000, lateness_ms=10_000)
    one = process(None, [Event(1_000, ("a",), {}, 0), Event(9_000, ("a",), {}, 1)], spec, MEASURES)
    assert sorted((r.start_ms, r.end_ms) for r in one.rows) == [(1_000, 6_000), (9_000, 14_000)]
    bridged = process(one.state, [Event(5_000, ("a",), {}, 2)], spec, MEASURES)
    assert sorted(bridged.removed) == [(1_000, 6_000, group_key(("a",))), (9_000, 14_000, group_key(("a",)))]
    assert [(r.start_ms, r.end_ms, r.events) for r in bridged.rows] == [(1_000, 14_000, 3)]


def test_measures_skip_what_is_not_a_number_and_order_first_and_last_by_time():
    events = [Event(5, ("a",), {"amount": "x", "label": "late in time"}, 0),
              Event(1, ("a",), {"amount": 4, "label": "early"}, 1),
              Event(3, ("a",), {"amount": None, "label": "middle"}, 2)]
    values = finish(_of(events, MEASURES), MEASURES)
    assert values == {"events": 3, "total": 4.0, "mean": 4.0, "low": 4.0, "high": 4.0,
                      "opened": "early", "closed_with": "late in time"}


def test_a_spec_that_cannot_work_is_refused():
    with pytest.raises(ValueError):
        WindowSpec("hopping", size_ms=1_000, advance_ms=2_000).check()
    with pytest.raises(ValueError):
        WindowSpec("session").check()
