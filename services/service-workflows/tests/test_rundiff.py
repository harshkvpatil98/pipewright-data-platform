"""Comparing two runs: what changed, and what only looks like it changed."""

from __future__ import annotations

from service_workflows.rundiff import diff_node_runs


def _node(key, *, status="succeeded", duration=1000, output=None, sequence=0, name=None):
    return {
        "node_key": key,
        "node_name": name or key,
        "node_type": "transformation",
        "status": status,
        "sequence": sequence,
        "duration_ms": duration,
        "output_json": output or {},
    }


def test_two_identical_runs_report_nothing_to_look_at():
    nodes = [_node("extract", output={"row_count": 100})]
    diff = diff_node_runs(nodes, [dict(node) for node in nodes])
    assert diff.identical is True
    assert diff.summary == "The two runs did the same work and produced the same numbers."


def test_a_status_change_leads_the_summary():
    left = [_node("gate", status="succeeded")]
    right = [_node("gate", status="failed")]
    diff = diff_node_runs(left, right)
    assert diff.nodes[0].verdict == "status_changed"
    assert "went from succeeded to failed" in diff.summary


def test_the_same_statuses_with_different_numbers_are_still_a_difference():
    """The failure mode worth catching: green run, wrong data."""
    left = [_node("extract", output={"row_count": 1000})]
    right = [_node("extract", output={"row_count": 400})]
    diff = diff_node_runs(left, right)

    assert diff.nodes[0].verdict == "output_changed"
    assert diff.nodes[0].changes == ["rows down 60% (1,000 to 400)"]
    assert "Same statuses, different data" in diff.summary


def test_a_count_rising_from_zero_is_described_without_dividing_by_it():
    left = [_node("gate", output={"rows_quarantined": 0})]
    right = [_node("gate", output={"rows_quarantined": 25})]
    assert diff_node_runs(left, right).nodes[0].changes == [
        "rows quarantined went from 0 to 25"
    ]


def test_non_numeric_outputs_are_compared_too():
    left = [_node("gate", output={"quality_status": "passed"})]
    right = [_node("gate", output={"quality_status": "failed"})]
    assert "quality status changed from 'passed' to 'failed'" in diff_node_runs(left, right).nodes[0].changes


def test_a_slower_node_is_reported_only_when_the_gap_is_real():
    fast = [_node("load", duration=100)]
    slightly = [_node("load", duration=140)]
    assert diff_node_runs(fast, slightly).nodes[0].verdict == "same"

    much = [_node("load", duration=9000)]
    diff = diff_node_runs([_node("load", duration=1000)], much)
    assert diff.nodes[0].verdict == "slower"
    assert diff.nodes[0].duration_change_percentage == 800.0
    assert "took 800% longer" in diff.summary


def test_a_faster_node_is_recognised_as_such():
    diff = diff_node_runs([_node("load", duration=8000)], [_node("load", duration=1000)])
    assert diff.nodes[0].verdict == "faster"


def test_nodes_are_matched_by_key_not_position():
    """A workflow edited between runs must not line up unrelated nodes."""
    left = [_node("extract", sequence=0), _node("publish", sequence=1)]
    right = [_node("extract", sequence=0), _node("validate", sequence=1), _node("publish", sequence=2)]
    diff = diff_node_runs(left, right)

    by_key = {node.node_key: node for node in diff.nodes}
    assert by_key["validate"].verdict == "added"
    assert by_key["publish"].verdict == "same"
    assert "node(s) added or removed" in diff.summary


def test_a_node_present_only_in_the_older_run_is_removed():
    diff = diff_node_runs([_node("legacy")], [])
    assert diff.nodes[0].verdict == "removed"
    assert diff.nodes[0].right_status is None


def test_comparing_two_empty_runs_says_so():
    assert diff_node_runs([], []).summary == "Neither run recorded any nodes."


def test_a_missing_duration_does_not_produce_a_bogus_percentage():
    diff = diff_node_runs([_node("skipped", duration=0)], [_node("skipped", duration=0)])
    assert diff.nodes[0].duration_change_percentage is None
