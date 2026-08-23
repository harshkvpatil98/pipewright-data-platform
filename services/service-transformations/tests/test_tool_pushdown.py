"""Tools push down, because tools are IR.

This is the claim the whole registry shape is justified by: a tool declares an
expression, and pushdown, lineage and type inference follow without a second
implementation. A claim like that is worth an actual test rather than a comment.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.types import STRING, timestamp
from shared_python.types.lattice import FLOAT64

import service_transformations.tools as tools
from service_transformations.ir import pandas_backend
from service_transformations.ir.expressions import supported_in
from service_transformations.ir.nodes import Node, Project, Scan
from service_transformations.ir.sql_backend import to_sql
from service_transformations.tools.apply import SOURCE, build

SCAN = Scan(
    source="orders",
    columns=(("sku", STRING), ("amount", FLOAT64), ("placed_at", timestamp())),
)

FRAME = pd.DataFrame(
    {
        "sku": ["ab-1", "cd-2", None],
        "amount": [10.5, 20.25, None],
        "placed_at": pd.to_datetime(["2026-08-23", "2026-01-05", None]),
    }
)


def node_for(config: dict) -> Node:
    return tools.build(SCAN, config)


class TestPushableToolsBecomeSql:
    @pytest.mark.parametrize(
        "config",
        [
            {"tool": "text.upper", "column": "sku"},
            {"tool": "text.trim", "column": "sku"},
            {"tool": "text.left", "column": "sku", "count": 2},
            {"tool": "text.contains", "column": "sku", "needle": "ab"},
            {"tool": "text.starts_with", "column": "sku", "prefix": "ab"},
            {"tool": "numeric.round", "column": "amount", "digits": 1},
            {"tool": "numeric.absolute", "column": "amount"},
            {"tool": "date.year", "column": "placed_at"},
            {"tool": "date.month", "column": "placed_at"},
            {"tool": "hash.md5", "column": "sku"},
            {"tool": "columns.keep_only", "columns": ["sku"]},
            {"tool": "rows.keep_top", "count": 10},
        ],
    )
    def test_it_produces_postgres_sql(self, config: dict) -> None:
        sql = to_sql(node_for(config), "postgres")
        assert "SELECT" in sql.upper()

    def test_the_sql_names_the_function_rather_than_approximating_it(self) -> None:
        sql = to_sql(node_for({"tool": "text.upper", "column": "sku"}), "postgres")
        assert "UPPER" in sql.upper()

    def test_starts_with_uses_position_not_like(self) -> None:
        """`x LIKE y || '%'` turns a % in the needle into a wildcard."""
        sql = to_sql(node_for({"tool": "text.starts_with", "column": "sku", "prefix": "10%"}), "postgres")
        assert "POSITION" in sql.upper()
        assert "LIKE" not in sql.upper()


class TestLocalOnlyToolsSaySo:
    """A tool with no honest SQL must be reported, never approximated."""

    @pytest.mark.parametrize(
        "config",
        [
            {"tool": "text.slugify", "column": "sku"},
            {"tool": "text.remove_accents", "column": "sku"},
            {"tool": "clean.phone", "column": "sku", "region": "US"},
            {"tool": "date.fiscal_year", "column": "placed_at", "start_month": 4},
            {"tool": "type.to_number", "column": "sku"},
        ],
    )
    def test_it_is_not_claimed_as_pushable(self, config: dict) -> None:
        node = node_for(config)
        assert isinstance(node, Project)
        pushable = all(
            supported_in("postgres", expression) for _, expression in node.projections
        )
        assert not pushable, f"{config['tool']} claims a lowering it should not have"

    def test_it_still_runs_locally(self) -> None:
        node = node_for({"tool": "text.slugify", "column": "sku"})
        result = pandas_backend.execute(node, {"orders": FRAME})
        assert result["sku"].tolist()[:2] == ["ab-1", "cd-2"]


class TestTypeInference:
    """A tool's output type comes from the IR, so the grid can format it."""

    def test_a_text_tool_produces_text(self) -> None:
        node = node_for({"tool": "text.upper", "column": "sku"})
        assert node.schema()["sku"].kind.value == "string"

    def test_a_length_produces_an_integer(self) -> None:
        node = node_for({"tool": "text.length", "column": "sku", "into": "n"})
        assert node.schema()["n"].kind.value == "int64"

    def test_a_check_produces_a_boolean(self) -> None:
        node = node_for({"tool": "check.is_email", "column": "sku", "into": "ok"})
        assert node.schema()["ok"].kind.value == "boolean"

    def test_a_date_extraction_produces_an_integer(self) -> None:
        node = node_for({"tool": "date.year", "column": "placed_at", "into": "y"})
        assert node.schema()["y"].kind.value == "int64"

    def test_the_original_columns_keep_their_types(self) -> None:
        node = node_for({"tool": "text.upper", "column": "sku"})
        assert node.schema()["amount"].kind.value == "float64"
        assert node.schema()["placed_at"].is_temporal


class TestPlannerSplitsAMixedPipeline:
    """The interesting case: some tools push, the rest run here."""

    def test_the_pushable_prefix_is_planned_and_the_rest_stays_local(self) -> None:
        from service_transformations.ir.planner import plan

        pushable = tools.build(SCAN, {"tool": "text.upper", "column": "sku"})
        mixed = tools.build(pushable, {"tool": "text.slugify", "column": "sku"})

        planned = plan(mixed, "postgresql")
        # The upper() half goes to the source; slugify stays here and says so.
        assert planned.sql is not None
        assert "UPPER" in planned.sql.upper()
        assert planned.pushed_count >= 1
        assert planned.local_count >= 1
        assert any(not decision.pushed for decision in planned.decisions)

    def test_a_wholly_pushable_pipeline_leaves_nothing_local(self) -> None:
        from service_transformations.ir.planner import plan

        node = tools.build(SCAN, {"tool": "text.upper", "column": "sku"})
        node = tools.build(node, {"tool": "numeric.round", "column": "amount", "digits": 1})
        planned = plan(node, "postgresql")
        assert planned.local_count == 0
        assert planned.pushed_count >= 2

    def test_a_local_only_source_pushes_nothing_and_explains(self) -> None:
        from service_transformations.ir.planner import plan

        node = tools.build(SCAN, {"tool": "text.upper", "column": "sku"})
        planned = plan(node, "csv")
        assert planned.fully_local
        assert planned.explain()


class TestExecutionAgreesWithTheLocalPath:
    """A tool run through the IR must equal the tool run through the step engine."""

    @pytest.mark.parametrize("name", sorted(tools.TOOLS))
    def test_ir_execution_equals_step_execution(self, name: str) -> None:
        from service_transformations.executor import apply_transformation_steps

        spec = tools.TOOLS[name]
        frame = pd.DataFrame(list(spec.example.rows))
        column = spec.example.column or (list(frame.columns)[0] if len(frame.columns) else None)
        config = {"tool": name, **spec.example.params}
        if column:
            config["column"] = column

        through_steps, _ = apply_transformation_steps(
            frame, [{"step_type": "tool", "config": config}]
        )
        through_ir = pandas_backend.execute(build(frame, config), {SOURCE: frame})
        pd.testing.assert_frame_equal(
            through_steps.reset_index(drop=True), through_ir.reset_index(drop=True)
        )
