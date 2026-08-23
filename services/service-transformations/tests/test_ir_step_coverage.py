"""The step-to-IR mappings that the main differential corpus does not reach.

Casts, value replacement, the two-dataset steps, and the paths that fall back
to an Extension. These matter because a mapping that is never exercised is a
mapping nobody has checked, and it will be wrong the first time someone uses it.
"""

from __future__ import annotations


import pandas as pd
import pytest

from shared_python.types import INT64, STRING, Kind
from service_transformations.ir.expressions import Column
from service_transformations.ir.from_steps import compile_step
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    IRError,
    Join,
    Project,
    Scan,
    SetOp,
)
from service_transformations.ir.pandas_backend import execute, register_extension
from service_transformations.steps import STEP_APPLY_FUNCTIONS

FRAME = pd.DataFrame(
    {
        "id": [1, 2, 3],
        "qty": ["10", "20", "x"],
        "region": ["eu", "us", "eu"],
        "note": ["a-b", "c-d", None],
    }
)
SCAN = Scan(
    "t", (("id", INT64), ("qty", STRING), ("region", STRING), ("note", STRING))
)
RIGHT = Scan("u", (("region", STRING), ("owner", STRING)))
RIGHT_FRAME = pd.DataFrame({"region": ["eu", "nordics"], "owner": ["ana", "nils"]})


@pytest.fixture(autouse=True, scope="module")
def _extensions():
    for step_type, handler in STEP_APPLY_FUNCTIONS.items():
        def make(fn):
            def run(frame, config):
                result, _ = fn(frame, config)
                return result
            return run
        register_extension(step_type, make(handler))
    yield


class TestCasts:
    def test_cast_changes_the_declared_type(self) -> None:
        node = compile_step(SCAN, "cast_column_types", {"mappings": {"qty": "int"}})
        assert node.schema()["qty"].kind in (Kind.INT64, Kind.INT32)

    def test_untouched_columns_keep_their_type(self) -> None:
        node = compile_step(SCAN, "cast_column_types", {"mappings": {"qty": "int"}})
        assert node.schema()["region"].kind is Kind.STRING

    def test_a_canonical_type_name_is_accepted(self) -> None:
        # The lattice's own vocabulary, not just the seven legacy words.
        node = compile_step(SCAN, "cast_column_types", {"casts": {"qty": "decimal(12,3)"}})
        assert node.schema()["qty"].kind is Kind.DECIMAL

    def test_an_unknown_cast_target_is_rejected_while_building(self) -> None:
        with pytest.raises(IRError, match="Unknown cast target"):
            compile_step(SCAN, "cast_column_types", {"casts": {"qty": "quaternion"}})

    def test_a_bad_value_becomes_null_rather_than_failing_the_run(self) -> None:
        node = compile_step(SCAN, "cast_column_types", {"mappings": {"qty": "int"}})
        result = execute(node, {"t": FRAME})
        assert list(result["qty"])[:2] == [10, 20]
        assert pd.isna(list(result["qty"])[2])


class TestValueOperations:
    def test_replace_values_maps_to_a_projection(self) -> None:
        node = compile_step(
            SCAN, "replace_values", {"columns": ["region"], "find": "eu", "replace": "EMEA"}
        )
        assert isinstance(node, Project)
        result = execute(node, {"t": FRAME})
        assert list(result["region"]) == ["EMEA", "us", "EMEA"]

    def test_fill_nulls_with_a_constant_is_a_projection(self) -> None:
        node = compile_step(
            SCAN, "fill_nulls",
            {"strategy": "constant", "columns": ["note"], "constant_value": "none"},
        )
        assert isinstance(node, Project)
        assert list(execute(node, {"t": FRAME})["note"]) == ["a-b", "c-d", "none"]

    def test_a_non_constant_fill_falls_back_to_an_extension(self) -> None:
        # Forward fill depends on row order, which is not a scalar expression.
        node = compile_step(SCAN, "fill_nulls", {"strategy": "forward", "columns": ["note"]})
        assert isinstance(node, Extension)

    def test_parse_dates_declares_a_timestamp(self) -> None:
        node = compile_step(SCAN, "parse_dates", {"columns": ["note"]})
        assert node.schema()["note"].kind is Kind.TIMESTAMP


class TestRowSteps:
    def test_drop_null_rows_any_keeps_only_complete_rows(self) -> None:
        node = compile_step(SCAN, "drop_null_rows", {"how": "any", "columns": ["note"]})
        assert len(execute(node, {"t": FRAME})) == 2

    def test_drop_null_rows_all_keeps_rows_with_any_value(self) -> None:
        # "all" means drop only when EVERY named column is null. An earlier
        # version ignored `how` and silently applied "any", deleting rows it
        # should have kept.
        node = compile_step(
            SCAN, "drop_null_rows", {"how": "all", "columns": ["region", "note"]}
        )
        assert len(execute(node, {"t": FRAME})) == 3

    def test_an_unknown_how_is_rejected(self) -> None:
        with pytest.raises(IRError, match="must be 'any' or 'all'"):
            compile_step(SCAN, "drop_null_rows", {"how": "sometimes"})

    def test_a_regex_filter_stays_local(self) -> None:
        # SQL LIKE is not the same language as a regex, so this must not be
        # pushed down as "close enough".
        node = compile_step(
            SCAN, "filter_rows",
            {"conditions": [{"column": "region", "operator": "contains", "value": "e"}]},
        )
        assert isinstance(node, Extension)

    def test_an_unsupported_filter_operator_is_rejected(self) -> None:
        with pytest.raises(IRError, match="Unsupported filter operator"):
            compile_step(
                SCAN, "filter_rows",
                {"conditions": [{"column": "id", "operator": "spaceship", "value": 1}]},
            )

    def test_remove_duplicates_maps_to_distinct(self) -> None:
        node = compile_step(SCAN, "remove_duplicates", {"subset": ["region"], "keep": "first"})
        assert isinstance(node, Distinct)
        assert node.subset == ("region",)

    def test_dropping_every_column_is_refused(self) -> None:
        with pytest.raises(IRError, match="leave nothing"):
            compile_step(SCAN, "drop_columns", {"columns": list(SCAN.schema())})


class TestTwoDatasetSteps:
    def test_a_join_without_a_resolved_right_side_is_an_extension(self) -> None:
        # The right dataset is resolved by StepContext at run time; without one
        # there is nothing to join to.
        node = compile_step(SCAN, "join_datasets", {"on": "region", "how": "inner"})
        assert isinstance(node, Extension)

    def test_a_join_with_a_right_side_becomes_a_join_node(self) -> None:
        node = compile_step(
            SCAN, "join_datasets",
            {"on": "region", "how": "inner", "_right_node": RIGHT},
        )
        assert isinstance(node, Join)
        result = execute(node, {"t": FRAME, "u": RIGHT_FRAME})
        assert len(result) == 2  # both eu rows match; us does not

    def test_a_join_supports_separate_key_names(self) -> None:
        node = compile_step(
            SCAN, "join_datasets",
            {"left_on": "region", "right_on": "region", "how": "left", "_right_node": RIGHT},
        )
        assert isinstance(node, Join)
        assert node.how == "left"

    def test_a_union_without_a_right_side_is_an_extension(self) -> None:
        node = compile_step(SCAN, "union_datasets", {})
        assert isinstance(node, Extension)

    def test_a_union_with_a_right_side_becomes_a_set_op(self) -> None:
        left = compile_step(SCAN, "select_columns", {"columns": ["region"]})
        right = Project(RIGHT, (("region", Column("region")),))
        node = compile_step(left, "union_datasets", {"_right_node": right})
        assert isinstance(node, SetOp)
        assert node.kind == "union_all"

    def test_distinct_union_is_requested_explicitly(self) -> None:
        left = compile_step(SCAN, "select_columns", {"columns": ["region"]})
        right = Project(RIGHT, (("region", Column("region")),))
        node = compile_step(left, "union_datasets", {"distinct": True, "_right_node": right})
        assert node.kind == "union"


class TestAggregateMapping:
    @pytest.mark.parametrize(
        ("function", "expected"),
        [("sum", "sum"), ("mean", "avg"), ("nunique", "count_distinct"), ("median", "median")],
    )
    def test_engine_function_names_map_to_ir_names(self, function: str, expected: str) -> None:
        node = compile_step(
            SCAN, "aggregate",
            {"group_by": ["region"], "aggregations": [{"column": "id", "function": function}]},
        )
        assert isinstance(node, Aggregate)
        assert node.aggregates[0][1].name == expected

    def test_an_unsupported_aggregate_is_rejected(self) -> None:
        with pytest.raises(IRError, match="Unsupported aggregate"):
            compile_step(
                SCAN, "aggregate",
                {"group_by": [], "aggregations": [{"column": "id", "function": "kurtosis"}]},
            )

    def test_the_default_alias_names_the_column_and_function(self) -> None:
        node = compile_step(
            SCAN, "aggregate",
            {"group_by": ["region"], "aggregations": [{"column": "id", "function": "sum"}]},
        )
        assert "id_sum" in node.schema()


class TestConfigContractsMatchTheEngine:
    """The IR must read the same config the engine reads.

    An earlier version of the cast mapping read `casts` while the step's own
    key is `mappings`, so the IR silently cast nothing while the engine cast
    everything. Nothing failed -- the IR simply produced a different answer,
    which is the worst kind of bug. These guards pin the shared vocabulary.
    """

    def test_every_engine_cast_target_is_understood_by_the_ir(self) -> None:
        from service_transformations.steps.common import ALLOWED_CAST_TARGET_TYPES

        for target in ALLOWED_CAST_TARGET_TYPES:
            node = compile_step(SCAN, "cast_column_types", {"mappings": {"qty": target}})
            assert node.schema()["qty"].kind is not Kind.UNKNOWN, target

    def test_the_ir_reads_the_key_the_step_requires(self) -> None:
        # `mappings` is the step's required field; reading anything else means
        # the IR quietly does nothing.
        node = compile_step(SCAN, "cast_column_types", {"mappings": {"qty": "int"}})
        assert node.schema()["qty"].kind is not Kind.STRING

    def test_every_engine_aggregate_function_is_understood_by_the_ir(self) -> None:
        from service_transformations.steps.aggregate import SUPPORTED_AGGREGATIONS

        for function in SUPPORTED_AGGREGATIONS:
            compile_step(
                SCAN,
                "aggregate",
                {"group_by": ["region"], "aggregations": [
                    {"column": "id", "function": function}]},
            )

    def test_every_engine_filter_operator_is_understood_by_the_ir(self) -> None:
        from service_transformations.steps.common import ALLOWED_FILTER_OPERATORS

        for operator in ALLOWED_FILTER_OPERATORS:
            value = ["eu"] if operator == "in" else "eu"
            compile_step(
                SCAN,
                "filter_rows",
                {"conditions": [{"column": "region", "operator": operator, "value": value}]},
            )
