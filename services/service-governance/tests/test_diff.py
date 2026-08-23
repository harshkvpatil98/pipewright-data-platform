"""The snapshot diff: what makes a version list readable."""

from __future__ import annotations

from service_governance.diff import diff_snapshots, summarise


def test_identical_snapshots_report_nothing():
    snapshot = {"name": "Nightly", "nodes": [{"node_key": "a"}]}
    result = diff_snapshots(snapshot, dict(snapshot))
    assert result.identical
    assert result.summary() == "No changes."


def test_a_changed_scalar_is_reported_with_both_values():
    result = diff_snapshots({"name": "old"}, {"name": "new"})
    assert [(c.path, c.kind, c.before, c.after) for c in result.changes] == [
        ("name", "changed", "old", "new")
    ]


def test_timestamps_that_move_on_every_save_are_ignored():
    """Otherwise every version would read 'changed updated at'."""
    before = {"name": "a", "updated_at": "2026-01-01", "execution_count": 1}
    after = {"name": "a", "updated_at": "2026-06-01", "execution_count": 9}
    assert diff_snapshots(before, after).identical


def test_a_list_is_matched_by_identity_not_position():
    """Inserting a step must not report every later step as changed."""
    before = {"nodes": [{"node_key": "a", "name": "A"}, {"node_key": "b", "name": "B"}]}
    after = {
        "nodes": [
            {"node_key": "a", "name": "A"},
            {"node_key": "new", "name": "New"},
            {"node_key": "b", "name": "B"},
        ]
    }
    result = diff_snapshots(before, after)
    assert [(c.kind, c.path) for c in result.changes] == [("added", "nodes[node_key=new]")]


def test_removing_an_entry_is_reported_once():
    before = {"nodes": [{"node_key": "a"}, {"node_key": "b"}]}
    after = {"nodes": [{"node_key": "a"}]}
    result = diff_snapshots(before, after)
    assert [(c.kind, c.path) for c in result.changes] == [("removed", "nodes[node_key=b]")]


def test_editing_inside_a_matched_entry_names_the_field():
    before = {"nodes": [{"node_key": "a", "config": {"table": "orders"}}]}
    after = {"nodes": [{"node_key": "a", "config": {"table": "orders_v2"}}]}
    result = diff_snapshots(before, after)
    assert result.changes[0].path == "nodes[node_key=a].config.table"
    assert result.changes[0].after == "orders_v2"


def test_lists_without_identity_fall_back_to_position():
    result = diff_snapshots({"tags": ["a", "b"]}, {"tags": ["a", "c"]})
    assert [(c.kind, c.path) for c in result.changes] == [("changed", "tags[1]")]


def test_a_shorter_list_reports_the_missing_tail():
    result = diff_snapshots({"tags": ["a", "b"]}, {"tags": ["a"]})
    assert [(c.kind, c.path) for c in result.changes] == [("removed", "tags[1]")]


def test_duplicate_identities_fall_back_to_position_rather_than_losing_entries():
    before = {"steps": [{"step_type": "trim"}, {"step_type": "trim"}]}
    after = {"steps": [{"step_type": "trim"}]}
    result = diff_snapshots(before, after)
    assert [(c.kind, c.path) for c in result.changes] == [("removed", "steps[1]")]


def test_creating_from_nothing_reports_the_whole_document():
    result = diff_snapshots(None, {"name": "Nightly"})
    assert not result.identical


def test_a_huge_diff_is_truncated_rather_than_unreadable():
    before = {f"key{index}": index for index in range(200)}
    after = {f"key{index}": index + 1 for index in range(200)}
    result = diff_snapshots(before, after)
    assert result.truncated
    assert len(result.changes) == 40
    assert "among other things" in result.summary()


def test_the_summary_reads_like_a_sentence():
    result = diff_snapshots(
        {"name": "a", "nodes": [{"node_key": "x"}]},
        {"name": "b", "nodes": [{"node_key": "x"}, {"node_key": "y"}]},
    )
    summary = result.summary()
    assert summary.startswith("Added ")
    assert summary.endswith(".")


def test_summarise_handles_one_two_and_many():
    from service_governance.diff import Change

    one = [Change(path="name", kind="changed")]
    two = [Change(path="name", kind="changed"), Change(path="enabled", kind="changed")]
    many = [Change(path=f"field{i}", kind="changed") for i in range(5)]

    assert summarise(one) == "Changed name."
    assert summarise(two) == "Changed name and enabled."
    assert "and 3 more" in summarise(many)
    assert summarise([]) == "No changes."
