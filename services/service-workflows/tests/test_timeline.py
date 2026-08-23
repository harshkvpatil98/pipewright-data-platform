"""Where a run's time went."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from service_workflows.timeline import build_timeline

START = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)


def _node(key, *, sequence, offset_seconds, duration_ms, status="succeeded"):
    started = START + timedelta(seconds=offset_seconds) if status != "skipped" else None
    return {
        "node_key": key,
        "node_name": key,
        "node_type": "transformation",
        "status": status,
        "sequence": sequence,
        "started_at": started,
        "finished_at": (started + timedelta(milliseconds=duration_ms)) if started else None,
        "duration_ms": duration_ms,
    }


def test_offsets_are_measured_from_the_start_of_the_run():
    timeline = build_timeline(
        run_started_at=START,
        run_finished_at=START + timedelta(seconds=10),
        node_runs=[
            _node("a", sequence=0, offset_seconds=0, duration_ms=2000),
            _node("b", sequence=1, offset_seconds=2, duration_ms=8000),
        ],
    )
    assert timeline.total_ms == 10_000
    assert [entry.offset_ms for entry in timeline.entries] == [0, 2000]


def test_the_dominant_step_is_called_out_by_name():
    timeline = build_timeline(
        run_started_at=START,
        run_finished_at=START + timedelta(seconds=10),
        node_runs=[
            _node("quick", sequence=0, offset_seconds=0, duration_ms=500),
            _node("slow", sequence=1, offset_seconds=1, duration_ms=9000),
        ],
    )
    assert timeline.slowest_node_key == "slow"
    assert "90% of the whole run" in timeline.summary


def test_evenly_spread_work_gets_a_different_sentence():
    timeline = build_timeline(
        run_started_at=START,
        run_finished_at=START + timedelta(seconds=9),
        node_runs=[
            _node("a", sequence=0, offset_seconds=0, duration_ms=3000),
            _node("b", sequence=1, offset_seconds=3, duration_ms=3000),
            _node("c", sequence=2, offset_seconds=6, duration_ms=3000),
        ],
    )
    assert "the slowest was" in timeline.summary
    assert "9.0s across 3 node(s)" in timeline.summary


def test_a_skipped_node_keeps_its_place_in_the_sequence():
    """A gap in the run is exactly what someone is looking for."""
    timeline = build_timeline(
        run_started_at=START,
        run_finished_at=START + timedelta(seconds=5),
        node_runs=[
            _node("ran", sequence=0, offset_seconds=0, duration_ms=5000),
            _node("skipped", sequence=1, offset_seconds=0, duration_ms=0, status="skipped"),
        ],
    )
    assert [entry.node_key for entry in timeline.entries] == ["ran", "skipped"]
    assert timeline.entries[1].offset_ms == 5000
    assert timeline.entries[1].duration_ms == 0


def test_a_run_still_in_flight_is_measured_from_what_has_finished():
    timeline = build_timeline(
        run_started_at=START,
        run_finished_at=None,
        node_runs=[_node("a", sequence=0, offset_seconds=0, duration_ms=4000)],
    )
    assert timeline.total_ms == 4000
    assert timeline.entries[0].share_percentage == 100.0


def test_a_run_with_no_nodes_says_so():
    timeline = build_timeline(run_started_at=START, run_finished_at=START, node_runs=[])
    assert timeline.entries == []
    assert timeline.summary == "This run recorded no nodes."


def test_naive_timestamps_are_read_as_utc():
    timeline = build_timeline(
        run_started_at=datetime(2026, 8, 21, 2, 0),
        run_finished_at=datetime(2026, 8, 21, 2, 0, 5),
        node_runs=[_node("a", sequence=0, offset_seconds=1, duration_ms=1000)],
    )
    assert timeline.total_ms == 5000
    assert timeline.entries[0].offset_ms == 1000
