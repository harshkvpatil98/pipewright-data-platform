"""Workflow graph structure, validation, and execution ordering.

This module is deliberately pure: no database, no HTTP, no pandas. A workflow is
a directed acyclic graph of nodes joined by conditional edges, and everything
about whether that graph is *runnable* is decided here so it can be unit tested
exhaustively and checked cheaply before a run is ever queued.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# The kinds of work a node can perform. Each maps to a handler in `nodes.py`.
NODE_TYPES: tuple[str, ...] = (
    "extraction",
    "transformation",
    "quality_gate",
    "drift_gate",
    "publish",
    "reverse_etl",
    "notify",
)

# When an edge is followed, based on how the upstream node finished.
EDGE_CONDITIONS: tuple[str, ...] = ("on_success", "on_failure", "always")

# Node keys are referenced from other nodes' configuration (`dataset_from`), so
# they are restricted to an identifier shape rather than free text.
NODE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

MAX_NODES = 200


@dataclass(frozen=True)
class GraphNode:
    key: str
    node_type: str


@dataclass(frozen=True)
class GraphEdge:
    from_key: str
    to_key: str
    condition: str = "on_success"


@dataclass(frozen=True)
class GraphIssue:
    """A structural problem. `code` is stable; `message` is for humans."""

    code: str
    message: str
    node_key: str | None = None


@dataclass
class GraphValidation:
    errors: list[GraphIssue] = field(default_factory=list)
    warnings: list[GraphIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": [
                {"code": issue.code, "message": issue.message, "node_key": issue.node_key}
                for issue in self.errors
            ],
            "warnings": [
                {"code": issue.code, "message": issue.message, "node_key": issue.node_key}
                for issue in self.warnings
            ],
        }


def find_cycle(nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> list[str] | None:
    """Return one cycle as a list of node keys, or None when the graph is acyclic.

    Depth-first search with three colours: white (unvisited), grey (on the
    current path), black (finished). Reaching a grey node means the path has
    looped, and the recorded stack gives the operator the actual cycle rather
    than a bare "cycle detected".
    """
    adjacency: dict[str, list[str]] = {node.key: [] for node in nodes}
    for edge in edges:
        if edge.from_key in adjacency and edge.to_key in adjacency:
            adjacency[edge.from_key].append(edge.to_key)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(adjacency, WHITE)
    path: list[str] = []

    def visit(key: str) -> list[str] | None:
        colour[key] = GREY
        path.append(key)
        for neighbour in adjacency[key]:
            if colour[neighbour] == GREY:
                # The cycle is the tail of the current path from `neighbour` on.
                start = path.index(neighbour)
                return [*path[start:], neighbour]
            if colour[neighbour] == WHITE:
                found = visit(neighbour)
                if found:
                    return found
        colour[key] = BLACK
        path.pop()
        return None

    for key in adjacency:
        if colour[key] == WHITE:
            cycle = visit(key)
            if cycle:
                return cycle
    return None


def topological_levels(nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> list[list[str]]:
    """Group node keys into dependency levels.

    Every node in a level depends only on earlier levels, so a level's nodes may
    run in parallel. Raises ValueError on a cyclic graph -- callers validate
    first, so reaching that means a programming error rather than bad input.
    """
    node_keys = [node.key for node in nodes]
    indegree = dict.fromkeys(node_keys, 0)
    adjacency: dict[str, list[str]] = {key: [] for key in node_keys}

    for edge in edges:
        if edge.from_key in adjacency and edge.to_key in indegree:
            adjacency[edge.from_key].append(edge.to_key)
            indegree[edge.to_key] += 1

    # Kahn's algorithm, draining one whole level at a time. Sorting keeps the
    # order stable so runs are reproducible and tests are deterministic.
    ready = sorted(key for key, degree in indegree.items() if degree == 0)
    levels: list[list[str]] = []
    seen = 0

    while ready:
        levels.append(ready)
        seen += len(ready)
        following: list[str] = []
        for key in ready:
            for neighbour in adjacency[key]:
                indegree[neighbour] -= 1
                if indegree[neighbour] == 0:
                    following.append(neighbour)
        ready = sorted(following)

    if seen != len(node_keys):
        raise ValueError("Cannot order a cyclic graph; validate before ordering.")
    return levels


def validate_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> GraphValidation:
    """Check that a graph is structurally runnable."""
    result = GraphValidation()

    if not nodes:
        result.errors.append(GraphIssue("empty_graph", "A workflow needs at least one node."))
        return result

    if len(nodes) > MAX_NODES:
        result.errors.append(
            GraphIssue(
                "too_many_nodes",
                f"A workflow supports at most {MAX_NODES} nodes; this one has {len(nodes)}.",
            )
        )

    seen_keys: set[str] = set()
    for node in nodes:
        if not NODE_KEY_PATTERN.match(node.key or ""):
            result.errors.append(
                GraphIssue(
                    "invalid_node_key",
                    f"Node key '{node.key}' must start with a letter and use only "
                    "lowercase letters, numbers, and underscores.",
                    node.key,
                )
            )
        elif node.key in seen_keys:
            result.errors.append(
                GraphIssue("duplicate_node_key", f"Two nodes share the key '{node.key}'.", node.key)
            )
        seen_keys.add(node.key)

        if node.node_type not in NODE_TYPES:
            result.errors.append(
                GraphIssue(
                    "unknown_node_type",
                    f"Node '{node.key}' has unsupported type '{node.node_type}'. "
                    f"Supported: {', '.join(NODE_TYPES)}.",
                    node.key,
                )
            )

    known = {node.key for node in nodes}
    seen_edges: set[tuple[str, str]] = set()

    for edge in edges:
        if edge.from_key not in known:
            result.errors.append(
                GraphIssue(
                    "unknown_edge_source",
                    f"An edge starts at '{edge.from_key}', which is not a node in this workflow.",
                    edge.from_key,
                )
            )
            continue
        if edge.to_key not in known:
            result.errors.append(
                GraphIssue(
                    "unknown_edge_target",
                    f"An edge points at '{edge.to_key}', which is not a node in this workflow.",
                    edge.to_key,
                )
            )
            continue
        if edge.from_key == edge.to_key:
            result.errors.append(
                GraphIssue(
                    "self_dependency",
                    f"Node '{edge.from_key}' cannot depend on itself.",
                    edge.from_key,
                )
            )
            continue
        if edge.condition not in EDGE_CONDITIONS:
            result.errors.append(
                GraphIssue(
                    "unknown_condition",
                    f"Edge '{edge.from_key}' -> '{edge.to_key}' has unsupported condition "
                    f"'{edge.condition}'. Supported: {', '.join(EDGE_CONDITIONS)}.",
                    edge.from_key,
                )
            )
            continue

        pair = (edge.from_key, edge.to_key)
        if pair in seen_edges:
            result.errors.append(
                GraphIssue(
                    "duplicate_edge",
                    f"There is more than one edge from '{edge.from_key}' to '{edge.to_key}'.",
                    edge.from_key,
                )
            )
        seen_edges.add(pair)

    # Only look for cycles once the edges are known to reference real nodes,
    # otherwise the traversal would report confusing paths.
    if not result.errors:
        cycle = find_cycle(nodes, edges)
        if cycle:
            result.errors.append(
                GraphIssue(
                    "cycle",
                    "These nodes depend on each other in a loop: " + " -> ".join(cycle) + ".",
                )
            )

    if not result.errors and len(nodes) > 1:
        connected = {edge.from_key for edge in edges} | {edge.to_key for edge in edges}
        for node in nodes:
            if node.key not in connected:
                result.warnings.append(
                    GraphIssue(
                        "isolated_node",
                        f"Node '{node.key}' has no connections, so it runs on its own.",
                        node.key,
                    )
                )

    return result


def should_run(
    node_key: str,
    edges: list[GraphEdge],
    statuses: dict[str, str],
) -> tuple[bool, str | None]:
    """Decide whether a node runs, given how its upstream nodes finished.

    A node with no incoming edges is a root and always runs. Otherwise *every*
    incoming edge must be satisfied, which is what makes a node with two parents
    a join rather than a race.

    Returns (run, reason_when_skipped).
    """
    incoming = [edge for edge in edges if edge.to_key == node_key]
    if not incoming:
        return True, None

    for edge in incoming:
        upstream_status = statuses.get(edge.from_key)

        if upstream_status is None or upstream_status == "skipped":
            return False, f"upstream '{edge.from_key}' did not run"

        if edge.condition == "on_success" and upstream_status != "succeeded":
            return False, f"upstream '{edge.from_key}' did not succeed"

        if edge.condition == "on_failure" and upstream_status != "failed":
            return False, f"upstream '{edge.from_key}' did not fail"

    return True, None
