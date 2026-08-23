"""Dataset-level lineage traversal."""

from __future__ import annotations

from service_lineage.graph import (
    DatasetNode,
    PipelineNode,
    build_graph,
    secondary_input_ids,
)

RAW = "aaaaaaaa-0000-0000-0000-000000000001"
CLEAN = "aaaaaaaa-0000-0000-0000-000000000002"
FINAL = "aaaaaaaa-0000-0000-0000-000000000003"
LOOKUP = "aaaaaaaa-0000-0000-0000-000000000004"


def _datasets(*ids: str) -> dict[str, DatasetNode]:
    return {
        dataset_id: DatasetNode(id=dataset_id, name=f"dataset-{dataset_id[-1]}", is_derived=dataset_id != RAW)
        for dataset_id in ids
    }


def test_secondary_inputs_are_read_out_of_step_configs():
    steps = [
        {"step_type": "join_datasets", "config": {"right_dataset_id": LOOKUP}},
        {"step_type": "union_datasets", "config": {"other_dataset_id": RAW}},
        {"step_type": "filter_rows", "config": {}},
    ]
    assert secondary_input_ids(steps) == ((LOOKUP, "joins"), (RAW, "unions"))


def test_joining_the_same_dataset_twice_is_one_edge():
    steps = [
        {"step_type": "join_datasets", "config": {"right_dataset_id": LOOKUP}},
        {"step_type": "join_datasets", "config": {"right_dataset_id": LOOKUP}},
    ]
    assert secondary_input_ids(steps) == ((LOOKUP, "joins"),)


def test_secondary_inputs_tolerate_a_malformed_step_list():
    assert secondary_input_ids(None) == ()
    assert secondary_input_ids([{"step_type": "join_datasets"}, "nonsense"]) == ()


def test_upstream_and_downstream_are_walked_from_the_focus():
    graph = build_graph(
        focus_dataset_id=CLEAN,
        datasets=_datasets(RAW, CLEAN, FINAL),
        pipelines=[
            PipelineNode(id="p1", name="Clean", base_dataset_id=RAW, output_dataset_ids=(CLEAN,)),
            PipelineNode(id="p2", name="Summarise", base_dataset_id=CLEAN, output_dataset_ids=(FINAL,)),
        ],
    )
    by_id = {node.id: node for node in graph.nodes}
    assert by_id[CLEAN].is_focus is True
    assert by_id[CLEAN].depth == 0
    assert by_id[RAW].depth < 0
    assert by_id[FINAL].depth > 0
    assert ("pipeline:p1", CLEAN, "produces") in {
        (edge.from_id, edge.to_id, edge.kind) for edge in graph.edges
    }


def test_a_joined_lookup_appears_upstream_of_the_output():
    graph = build_graph(
        focus_dataset_id=CLEAN,
        datasets=_datasets(RAW, CLEAN, LOOKUP),
        pipelines=[
            PipelineNode(
                id="p1",
                name="Enrich",
                base_dataset_id=RAW,
                secondary_inputs=((LOOKUP, "joins"),),
                output_dataset_ids=(CLEAN,),
            )
        ],
    )
    kinds = {(edge.from_id, edge.kind) for edge in graph.edges}
    assert (LOOKUP, "joins") in kinds
    assert (RAW, "consumes") in kinds


def test_a_dataset_used_only_as_a_join_target_still_finds_its_consumers():
    graph = build_graph(
        focus_dataset_id=LOOKUP,
        datasets=_datasets(RAW, CLEAN, LOOKUP),
        pipelines=[
            PipelineNode(
                id="p1",
                name="Enrich",
                base_dataset_id=RAW,
                secondary_inputs=((LOOKUP, "joins"),),
                output_dataset_ids=(CLEAN,),
            )
        ],
    )
    ids = {node.id for node in graph.nodes}
    assert "pipeline:p1" in ids
    assert CLEAN in ids


def test_the_walk_stops_at_the_depth_limit_and_says_so():
    datasets = _datasets(RAW, CLEAN, FINAL)
    graph = build_graph(
        focus_dataset_id=RAW,
        datasets=datasets,
        pipelines=[
            PipelineNode(id="p1", name="Clean", base_dataset_id=RAW, output_dataset_ids=(CLEAN,)),
            PipelineNode(id="p2", name="Summarise", base_dataset_id=CLEAN, output_dataset_ids=(FINAL,)),
        ],
        max_depth=2,
    )
    assert graph.truncated is True
    assert FINAL not in {node.id for node in graph.nodes}


def test_a_missing_focus_dataset_yields_an_empty_graph():
    graph = build_graph(focus_dataset_id="nope", datasets=_datasets(RAW), pipelines=[])
    assert graph.nodes == []
    assert graph.edges == []


def test_a_cycle_between_pipelines_does_not_hang_the_walk():
    """Datasets should never cycle, but a corrupt row must not loop forever."""
    graph = build_graph(
        focus_dataset_id=RAW,
        datasets=_datasets(RAW, CLEAN),
        pipelines=[
            PipelineNode(id="p1", name="A", base_dataset_id=RAW, output_dataset_ids=(CLEAN,)),
            PipelineNode(id="p2", name="B", base_dataset_id=CLEAN, output_dataset_ids=(RAW,)),
        ],
        max_depth=4,
    )
    assert {node.id for node in graph.nodes} == {RAW, CLEAN, "pipeline:p1", "pipeline:p2"}
