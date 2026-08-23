"""Dataset-level lineage: which datasets and pipelines feed which.

Column lineage answers "what is this column made of". This answers the coarser
question that comes first: "where did this table come from, and what reads it".
The two are shown together because neither is much use alone.

Nothing here touches the database. The caller loads a project's datasets and
pipelines once and hands them over as plain records, which keeps the traversal
testable and stops it from issuing a query per hop.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

# How far to walk in each direction. Beyond this the picture stops being
# readable, and a person who needs more can re-focus on a further node.
DEFAULT_MAX_DEPTH = 3


@dataclass(frozen=True)
class DatasetNode:
    id: str
    name: str
    is_derived: bool = False
    source_name: str | None = None
    row_count: int | None = None


@dataclass(frozen=True)
class PipelineNode:
    id: str
    name: str
    base_dataset_id: str
    # Datasets pulled in by join or union steps, with the step type that did it.
    secondary_inputs: tuple[tuple[str, str], ...] = ()
    output_dataset_ids: tuple[str, ...] = ()


@dataclass
class GraphNode:
    id: str
    kind: str  # "dataset" | "pipeline"
    name: str
    subtitle: str | None
    depth: int
    is_focus: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "subtitle": self.subtitle,
            "depth": self.depth,
            "is_focus": self.is_focus,
        }


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    kind: str  # "produces" | "consumes" | "joins" | "unions"
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "kind": self.kind,
            "label": self.label,
        }


@dataclass
class LineageGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    truncated: bool = False


def secondary_input_ids(steps: list[dict[str, Any]] | None) -> tuple[tuple[str, str], ...]:
    """Dataset ids a pipeline's steps pull in besides its base dataset."""
    found: list[tuple[str, str]] = []
    for raw in steps or []:
        if not isinstance(raw, dict):
            continue
        config = raw.get("config")
        config = config if isinstance(config, dict) else {}
        step_type = raw.get("step_type")
        if step_type == "join_datasets":
            dataset_id = config.get("right_dataset_id")
            if isinstance(dataset_id, str) and dataset_id:
                found.append((dataset_id, "joins"))
        elif step_type == "union_datasets":
            dataset_id = config.get("other_dataset_id")
            if isinstance(dataset_id, str) and dataset_id:
                found.append((dataset_id, "unions"))
    # Preserve order but drop repeats: joining the same dataset twice is one edge.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for entry in found:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return tuple(unique)


def build_graph(
    *,
    focus_dataset_id: str,
    datasets: dict[str, DatasetNode],
    pipelines: list[PipelineNode],
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> LineageGraph:
    """Walk out from one dataset in both directions."""

    graph = LineageGraph()
    placed: dict[str, GraphNode] = {}
    edge_keys: set[tuple[str, str, str]] = set()

    # Pipelines indexed by what they read and what they write.
    by_base: dict[str, list[PipelineNode]] = {}
    by_secondary: dict[str, list[PipelineNode]] = {}
    by_output: dict[str, list[PipelineNode]] = {}
    for pipeline in pipelines:
        by_base.setdefault(pipeline.base_dataset_id, []).append(pipeline)
        for dataset_id, _kind in pipeline.secondary_inputs:
            by_secondary.setdefault(dataset_id, []).append(pipeline)
        for dataset_id in pipeline.output_dataset_ids:
            by_output.setdefault(dataset_id, []).append(pipeline)

    def place(node_id: str, kind: str, name: str, subtitle: str | None, depth: int) -> GraphNode:
        existing = placed.get(node_id)
        if existing is not None:
            # Keep whichever placement is closest to the focus.
            if abs(depth) < abs(existing.depth):
                existing.depth = depth
            return existing
        node = GraphNode(id=node_id, kind=kind, name=name, subtitle=subtitle, depth=depth)
        placed[node_id] = node
        graph.nodes.append(node)
        return node

    def connect(from_id: str, to_id: str, kind: str, label: str | None = None) -> None:
        key = (from_id, to_id, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        graph.edges.append(GraphEdge(from_id=from_id, to_id=to_id, kind=kind, label=label))

    def dataset_subtitle(dataset: DatasetNode) -> str:
        if dataset.source_name:
            return f"from {dataset.source_name}"
        return "derived" if dataset.is_derived else "uploaded"

    focus = datasets.get(focus_dataset_id)
    if focus is None:
        return graph

    focus_node = place(focus.id, "dataset", focus.name, dataset_subtitle(focus), 0)
    focus_node.is_focus = True

    # ---- upstream: what produced this dataset ----
    queue: deque[tuple[str, int]] = deque([(focus_dataset_id, 0)])
    seen_up: set[str] = {focus_dataset_id}
    while queue:
        dataset_id, depth = queue.popleft()
        if depth <= -max_depth:
            graph.truncated = True
            continue
        for pipeline in by_output.get(dataset_id, []):
            pipeline_node_id = f"pipeline:{pipeline.id}"
            place(pipeline_node_id, "pipeline", pipeline.name, "transformation", depth - 1)
            connect(pipeline_node_id, dataset_id, "produces")

            inputs: list[tuple[str, str]] = [(pipeline.base_dataset_id, "consumes")]
            inputs.extend(pipeline.secondary_inputs)
            for input_id, kind in inputs:
                upstream = datasets.get(input_id)
                if upstream is None:
                    continue
                place(input_id, "dataset", upstream.name, dataset_subtitle(upstream), depth - 2)
                connect(input_id, pipeline_node_id, kind)
                if input_id not in seen_up:
                    seen_up.add(input_id)
                    queue.append((input_id, depth - 2))

    # ---- downstream: what reads this dataset ----
    queue = deque([(focus_dataset_id, 0)])
    seen_down: set[str] = {focus_dataset_id}
    while queue:
        dataset_id, depth = queue.popleft()
        if depth >= max_depth:
            graph.truncated = True
            continue
        consumers = [(pipeline, "consumes") for pipeline in by_base.get(dataset_id, [])]
        consumers.extend(
            (pipeline, kind)
            for pipeline in by_secondary.get(dataset_id, [])
            for target_id, kind in pipeline.secondary_inputs
            if target_id == dataset_id
        )
        for pipeline, kind in consumers:
            pipeline_node_id = f"pipeline:{pipeline.id}"
            place(pipeline_node_id, "pipeline", pipeline.name, "transformation", depth + 1)
            connect(dataset_id, pipeline_node_id, kind)

            for output_id in pipeline.output_dataset_ids:
                downstream = datasets.get(output_id)
                if downstream is None:
                    continue
                place(output_id, "dataset", downstream.name, dataset_subtitle(downstream), depth + 2)
                connect(pipeline_node_id, output_id, "produces")
                if output_id not in seen_down:
                    seen_down.add(output_id)
                    queue.append((output_id, depth + 2))

    graph.nodes.sort(key=lambda node: (node.depth, node.kind, node.name))
    return graph
