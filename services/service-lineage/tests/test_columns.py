"""Column lineage: what each step does to the column list, and back-tracing."""

from __future__ import annotations

import pytest
from service_transformations.steps import ALL_STEP_TYPES

from service_lineage.columns import (
    DYNAMIC_COLUMN,
    KNOWN_STEP_TYPES,
    build_pipeline_lineage,
)


def _step(step_type: str, **config):
    return {"step_type": step_type, "config": config}


def test_every_executable_step_type_is_known_to_lineage():
    """A new transform step must teach lineage what it does, or lineage lies."""
    assert KNOWN_STEP_TYPES == set(ALL_STEP_TYPES)


def test_columns_pass_through_untouched_steps_without_edges():
    lineage = build_pipeline_lineage(
        base_columns=["id", "amount"],
        steps=[_step("limit_rows", count=10)],
    )
    assert lineage.output_columns == ["id", "amount"]
    assert lineage.steps[0].edges == []
    assert lineage.trace("amount").origins[0].column == "amount"


def test_rename_is_followed_when_tracing():
    lineage = build_pipeline_lineage(
        base_columns=["region", "amount"],
        steps=[_step("rename_columns", mappings={"region": "market"})],
    )
    assert lineage.output_columns == ["market", "amount"]
    assert [origin.column for origin in lineage.trace("market").origins] == ["region"]


def test_derive_traces_through_to_every_referenced_column():
    lineage = build_pipeline_lineage(
        base_columns=["first", "last", "id"],
        steps=[_step("derive_column", target_column="full", expression='concat(first, " ", last)')],
    )
    assert lineage.output_columns == ["first", "last", "id", "full"]
    assert [origin.column for origin in lineage.trace("full").origins] == ["first", "last"]


def test_a_constant_expression_has_no_parent_column():
    lineage = build_pipeline_lineage(
        base_columns=["id"],
        steps=[_step("derive_column", target_column="flag", expression="1")],
    )
    trace = lineage.trace("flag")
    assert [origin.column for origin in trace.origins] == ["flag"]
    assert trace.origins[0].created_at_step == 0


def test_function_names_are_not_mistaken_for_columns():
    lineage = build_pipeline_lineage(
        base_columns=["price"],
        steps=[_step("derive_column", target_column="rounded", expression="round(price, 2)")],
    )
    assert [origin.column for origin in lineage.trace("rounded").origins] == ["price"]


def test_aggregate_replaces_the_column_list_with_keys_and_aliases():
    lineage = build_pipeline_lineage(
        base_columns=["region", "amount", "notes"],
        steps=[
            _step(
                "aggregate",
                group_by=["region"],
                aggregations=[{"column": "amount", "function": "sum", "alias": "total"}],
            )
        ],
    )
    assert lineage.output_columns == ["region", "total"]
    assert [origin.column for origin in lineage.trace("total").origins] == ["amount"]


def test_aggregate_without_an_alias_uses_the_engines_default_name():
    lineage = build_pipeline_lineage(
        base_columns=["region", "amount"],
        steps=[
            _step(
                "aggregate",
                group_by=["region"],
                aggregations=[{"column": "amount", "function": "sum"}],
            )
        ],
    )
    assert lineage.output_columns == ["region", "amount_sum"]


def test_split_adds_parts_and_can_drop_the_original():
    lineage = build_pipeline_lineage(
        base_columns=["name"],
        steps=[_step("split_column", column="name", delimiter=" ", into=["first", "last"], drop_original=True)],
    )
    assert lineage.output_columns == ["first", "last"]
    assert [origin.column for origin in lineage.trace("last").origins] == ["name"]


def test_drop_and_select_remove_columns_from_the_output():
    lineage = build_pipeline_lineage(
        base_columns=["a", "b", "c"],
        steps=[_step("drop_columns", columns=["b"]), _step("select_columns", columns=["c", "a"])],
    )
    assert lineage.output_columns == ["c", "a"]


def test_unpivot_turns_column_names_into_data():
    lineage = build_pipeline_lineage(
        base_columns=["id", "jan", "feb"],
        steps=[_step("unpivot", id_columns=["id"])],
    )
    assert lineage.output_columns == ["id", "variable", "value"]
    # Both the melted columns feed the value column.
    assert [origin.column for origin in lineage.trace("value").origins] == ["feb", "jan"]


def test_pivot_output_columns_are_marked_dynamic():
    lineage = build_pipeline_lineage(
        base_columns=["region", "month", "amount"],
        steps=[_step("pivot", index=["region"], columns="month", values="amount")],
    )
    assert lineage.output_columns == ["region", DYNAMIC_COLUMN]
    assert lineage.dynamic is True
    assert any("only known once the pipeline runs" in note for note in lineage.steps[0].notes)


def test_join_suffixes_only_the_colliding_right_columns():
    right = "11111111-1111-1111-1111-111111111111"
    lineage = build_pipeline_lineage(
        base_columns=["id", "name"],
        steps=[
            _step(
                "join_datasets",
                right_dataset_id=right,
                left_on=["id"],
                right_on=["id"],
                select_right_columns=["name", "tier"],
            )
        ],
    )
    # 'id' is a same-named key so pandas keeps one; 'name' collides so it is suffixed.
    assert lineage.output_columns == ["id", "name", "name_right", "tier"]
    origins = lineage.trace("tier").origins
    assert origins[0].dataset_id == right


def test_join_with_an_unresolvable_right_dataset_is_partial_not_wrong():
    lineage = build_pipeline_lineage(
        base_columns=["id"],
        steps=[
            _step(
                "join_datasets",
                right_dataset_id="22222222-2222-2222-2222-222222222222",
                left_on=["id"],
                right_on=["id"],
            )
        ],
    )
    assert lineage.dynamic is True
    assert lineage.output_columns == ["id"]


def test_union_resolves_the_other_datasets_columns():
    other = "33333333-3333-3333-3333-333333333333"
    lineage = build_pipeline_lineage(
        base_columns=["id", "amount"],
        steps=[_step("union_datasets", other_dataset_id=other)],
        resolve_schema=lambda dataset_id: ["id", "amount", "channel"] if dataset_id == other else None,
    )
    assert lineage.output_columns == ["id", "amount", "channel"]


def test_union_with_intersect_keeps_only_shared_columns():
    other = "44444444-4444-4444-4444-444444444444"
    lineage = build_pipeline_lineage(
        base_columns=["id", "amount", "notes"],
        steps=[_step("union_datasets", other_dataset_id=other, column_strategy="intersect")],
        resolve_schema=lambda _dataset_id: ["id", "amount"],
    )
    assert lineage.output_columns == ["id", "amount"]


def test_reads_are_recorded_separately_from_edges():
    lineage = build_pipeline_lineage(
        base_columns=["id", "region"],
        steps=[_step("filter_rows", conditions=[{"column": "region", "operator": "equals", "value": "EU"}])],
    )
    step = lineage.steps[0]
    assert step.edges == []
    assert [(read.column, read.purpose) for read in step.reads] == [("region", "filter")]


def test_dedupe_without_a_subset_reads_every_column_but_names_none():
    lineage = build_pipeline_lineage(
        base_columns=["id", "region"],
        steps=[_step("remove_duplicates")],
    )
    step = lineage.steps[0]
    assert {read.column for read in step.reads} == {"id", "region"}
    assert step.named_columns == []


def test_a_configured_dedupe_subset_names_its_columns():
    lineage = build_pipeline_lineage(
        base_columns=["id", "region"],
        steps=[_step("remove_duplicates", subset=["id"])],
    )
    assert lineage.steps[0].named_columns == ["id"]


def test_an_unknown_step_type_degrades_loudly():
    lineage = build_pipeline_lineage(
        base_columns=["id"],
        steps=[{"step_type": "teleport_rows", "config": {}}],
    )
    assert lineage.dynamic is True
    assert any("not known to lineage" in note for note in lineage.steps[0].notes)


def test_added_and_removed_columns_are_reported_per_step():
    lineage = build_pipeline_lineage(
        base_columns=["id", "name"],
        steps=[_step("split_column", column="name", delimiter=" ", into=["first"], drop_original=True)],
    )
    step = lineage.steps[0]
    assert step.added_columns == ["first"]
    assert step.removed_columns == ["name"]


def test_a_long_chain_traces_all_the_way_back():
    lineage = build_pipeline_lineage(
        base_columns=["raw_amount", "raw_region", "junk"],
        steps=[
            _step("rename_columns", mappings={"raw_amount": "amount", "raw_region": "region"}),
            _step("cast_column_types", mappings={"amount": "float"}),
            _step("derive_column", target_column="net", expression="amount * 0.8"),
            _step("drop_columns", columns=["junk"]),
            _step(
                "aggregate",
                group_by=["region"],
                aggregations=[{"column": "net", "function": "sum", "alias": "net_total"}],
            ),
        ],
    )
    assert lineage.output_columns == ["region", "net_total"]
    assert [origin.column for origin in lineage.trace("net_total").origins] == ["raw_amount"]
    assert [origin.column for origin in lineage.trace("region").origins] == ["raw_region"]


@pytest.mark.parametrize("column", ["raw_amount", "raw_region"])
def test_downstream_of_finds_the_outputs_a_base_column_reaches(column):
    lineage = build_pipeline_lineage(
        base_columns=["raw_amount", "raw_region"],
        steps=[
            _step("rename_columns", mappings={"raw_amount": "amount", "raw_region": "region"}),
            _step(
                "aggregate",
                group_by=["region"],
                aggregations=[{"column": "amount", "function": "sum", "alias": "total"}],
            ),
        ],
    )
    assert lineage.downstream_of(column) != []
