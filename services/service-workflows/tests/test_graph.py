from __future__ import annotations

import pytest

from service_workflows.graph import (
    MAX_NODES,
    GraphEdge,
    GraphNode,
    find_cycle,
    should_run,
    topological_levels,
    validate_graph,
)


def node(key: str, node_type: str = "transformation") -> GraphNode:
    return GraphNode(key=key, node_type=node_type)


def edge(source: str, target: str, condition: str = "on_success") -> GraphEdge:
    return GraphEdge(from_key=source, to_key=target, condition=condition)


def codes(validation) -> set[str]:
    return {issue.code for issue in validation.errors}


# ----------------------------------------------------------------- validation


def test_linear_graph_is_valid() -> None:
    result = validate_graph(
        [node("extract", "extraction"), node("clean"), node("publish", "publish")],
        [edge("extract", "clean"), edge("clean", "publish")],
    )
    assert result.valid
    assert result.errors == []


def test_empty_graph_is_rejected() -> None:
    assert "empty_graph" in codes(validate_graph([], []))


def test_duplicate_node_keys_are_rejected() -> None:
    result = validate_graph([node("a"), node("a")], [])
    assert "duplicate_node_key" in codes(result)


@pytest.mark.parametrize("key", ["", "1abc", "Has-Caps", "with space", "trailing-", "a" * 65])
def test_invalid_node_keys_are_rejected(key: str) -> None:
    assert "invalid_node_key" in codes(validate_graph([node(key)], []))


def test_unknown_node_type_is_rejected() -> None:
    result = validate_graph([node("a", "teleport")], [])
    assert "unknown_node_type" in codes(result)


def test_edge_to_missing_node_is_rejected() -> None:
    result = validate_graph([node("a")], [edge("a", "ghost")])
    assert "unknown_edge_target" in codes(result)


def test_edge_from_missing_node_is_rejected() -> None:
    result = validate_graph([node("a")], [edge("ghost", "a")])
    assert "unknown_edge_source" in codes(result)


def test_self_dependency_is_rejected() -> None:
    result = validate_graph([node("a")], [edge("a", "a")])
    assert "self_dependency" in codes(result)


def test_duplicate_edge_is_rejected() -> None:
    result = validate_graph([node("a"), node("b")], [edge("a", "b"), edge("a", "b")])
    assert "duplicate_edge" in codes(result)


def test_two_edges_with_different_conditions_are_still_duplicates() -> None:
    """One upstream cannot both require success and require failure of the same pair."""
    result = validate_graph(
        [node("a"), node("b")], [edge("a", "b", "on_success"), edge("a", "b", "on_failure")]
    )
    assert "duplicate_edge" in codes(result)


def test_unknown_condition_is_rejected() -> None:
    result = validate_graph([node("a"), node("b")], [edge("a", "b", "on_tuesday")])
    assert "unknown_condition" in codes(result)


def test_node_limit_is_enforced() -> None:
    nodes = [node(f"n{index}") for index in range(MAX_NODES + 1)]
    assert "too_many_nodes" in codes(validate_graph(nodes, []))


def test_isolated_node_is_a_warning_not_an_error() -> None:
    result = validate_graph([node("a"), node("b"), node("c")], [edge("a", "b")])
    assert result.valid
    assert [issue.code for issue in result.warnings] == ["isolated_node"]
    assert result.warnings[0].node_key == "c"


def test_single_node_graph_produces_no_isolation_warning() -> None:
    result = validate_graph([node("only")], [])
    assert result.valid
    assert result.warnings == []


def test_validation_serialises_for_the_api() -> None:
    payload = validate_graph([node("a"), node("b")], [edge("a", "a")]).to_dict()
    assert payload["valid"] is False
    assert payload["errors"][0]["code"] == "self_dependency"


# --------------------------------------------------------------------- cycles


def test_acyclic_graph_has_no_cycle() -> None:
    assert find_cycle([node("a"), node("b")], [edge("a", "b")]) is None


def test_direct_cycle_is_found() -> None:
    cycle = find_cycle([node("a"), node("b")], [edge("a", "b"), edge("b", "a")])
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b"}


def test_long_cycle_is_found_and_reported_as_a_path() -> None:
    nodes = [node("a"), node("b"), node("c"), node("d")]
    edges = [edge("a", "b"), edge("b", "c"), edge("c", "d"), edge("d", "b")]
    cycle = find_cycle(nodes, edges)
    assert cycle is not None
    # The loop is b -> c -> d -> b; 'a' feeds it but is not part of it.
    assert "a" not in cycle
    assert set(cycle) == {"b", "c", "d"}


def test_cycle_is_reported_as_a_validation_error_with_the_path() -> None:
    result = validate_graph(
        [node("a"), node("b"), node("c")],
        [edge("a", "b"), edge("b", "c"), edge("c", "a")],
    )
    assert "cycle" in codes(result)
    message = next(issue.message for issue in result.errors if issue.code == "cycle")
    assert "->" in message


def test_diamond_is_not_a_cycle() -> None:
    """Two paths that rejoin are a legitimate DAG, not a loop."""
    nodes = [node("a"), node("b"), node("c"), node("d")]
    edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")]
    assert find_cycle(nodes, edges) is None
    assert validate_graph(nodes, edges).valid


# ------------------------------------------------------------------- ordering


def test_linear_graph_orders_one_node_per_level() -> None:
    levels = topological_levels(
        [node("a"), node("b"), node("c")], [edge("a", "b"), edge("b", "c")]
    )
    assert levels == [["a"], ["b"], ["c"]]


def test_independent_nodes_share_a_level() -> None:
    levels = topological_levels([node("a"), node("b"), node("c")], [edge("a", "c"), edge("b", "c")])
    assert levels == [["a", "b"], ["c"]]


def test_diamond_orders_middle_nodes_together() -> None:
    levels = topological_levels(
        [node("a"), node("b"), node("c"), node("d")],
        [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")],
    )
    assert levels == [["a"], ["b", "c"], ["d"]]


def test_node_waits_for_its_deepest_dependency() -> None:
    """`d` depends on both `a` and `c`, so it cannot run until after `c`."""
    levels = topological_levels(
        [node("a"), node("b"), node("c"), node("d")],
        [edge("a", "b"), edge("b", "c"), edge("a", "d"), edge("c", "d")],
    )
    assert levels == [["a"], ["b"], ["c"], ["d"]]


def test_ordering_is_deterministic() -> None:
    nodes = [node("z"), node("m"), node("a")]
    assert topological_levels(nodes, []) == [["a", "m", "z"]]


def test_ordering_a_cyclic_graph_raises() -> None:
    with pytest.raises(ValueError, match="cyclic"):
        topological_levels([node("a"), node("b")], [edge("a", "b"), edge("b", "a")])


# --------------------------------------------------------- conditional gating


def test_root_node_always_runs() -> None:
    assert should_run("a", [], {}) == (True, None)


def test_node_runs_when_upstream_succeeded() -> None:
    run, reason = should_run("b", [edge("a", "b")], {"a": "succeeded"})
    assert run is True
    assert reason is None


def test_node_skips_when_upstream_failed() -> None:
    run, reason = should_run("b", [edge("a", "b")], {"a": "failed"})
    assert run is False
    assert "did not succeed" in reason


def test_on_failure_edge_runs_only_after_failure() -> None:
    edges = [edge("a", "cleanup", "on_failure")]
    assert should_run("cleanup", edges, {"a": "failed"})[0] is True
    assert should_run("cleanup", edges, {"a": "succeeded"})[0] is False


def test_always_edge_runs_after_either_outcome() -> None:
    edges = [edge("a", "notify", "always")]
    assert should_run("notify", edges, {"a": "succeeded"})[0] is True
    assert should_run("notify", edges, {"a": "failed"})[0] is True


def test_always_edge_still_skips_when_upstream_was_skipped() -> None:
    """'always' means either outcome, not 'even if it never ran'."""
    run, reason = should_run("notify", [edge("a", "notify", "always")], {"a": "skipped"})
    assert run is False
    assert "did not run" in reason


def test_join_requires_every_upstream() -> None:
    edges = [edge("a", "join"), edge("b", "join")]
    assert should_run("join", edges, {"a": "succeeded", "b": "succeeded"})[0] is True
    assert should_run("join", edges, {"a": "succeeded", "b": "failed"})[0] is False


def test_missing_upstream_status_skips_rather_than_crashing() -> None:
    run, reason = should_run("b", [edge("a", "b")], {})
    assert run is False
    assert "did not run" in reason


def test_every_node_type_the_engine_can_run_is_a_valid_node_type():
    """The gap this closes: a handler existed that the graph would reject.

    `drift_gate` shipped with a working handler and no entry here, so the
    executor could run it but no workflow could contain it -- and every test
    called the handler directly, so nothing noticed.
    """
    from service_workflows.graph import NODE_TYPES
    from service_workflows.nodes import NODE_HANDLERS

    assert set(NODE_TYPES) == set(NODE_HANDLERS)
