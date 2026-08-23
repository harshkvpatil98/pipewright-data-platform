"""Pushdown must not change the answer.

The planner rewrites the user's computation into SQL and runs it somewhere
else. A query that returns *nearly* the right answer is worse than one that
refuses, because nobody notices -- so every tree in the corpus is executed both
ways and the results are compared value for value.

This is the same discipline as `test_ir_differential.py`, one level up: that
proves the two backends agree, this proves the *split* between them does.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.expressions import Call, Case, Column, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Join,
    Distinct,
    Extension,
    Filter,
    Limit,
    Node,
    Project,
    Scan,
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute, register_extension
from service_transformations.ir.planner import plan
from service_transformations.ir.run_plan import execute_plan
from service_transformations.ir.surfaces import Surface, surface_for

ORDERS = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6, 7, 8],
        "region": ["eu", "us", "eu", "apac", "us", "eu", None, "apac"],
        "amount": [10.0, 250.0, 300.0, 75.5, 50.0, 120.0, 40.0, None],
        "label": ["a", "B", "c", "D", "e", "F", "g", None],
    }
)

SCAN = Scan(
    "orders",
    (("id", INT64), ("region", STRING), ("amount", FLOAT64), ("label", STRING)),
)


@pytest.fixture(scope="module")
def db():
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("orders", connection, index=False)
    yield connection
    connection.close()


@pytest.fixture(autouse=True, scope="module")
def _extension_handler():
    # A stand-in for a step the algebra cannot model: it must run locally, and
    # the planner must stop the prefix at it.
    register_extension("reverse_rows", lambda frame, _config: frame.iloc[::-1])
    yield


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        series = frame[column].reset_index(drop=True)
        numeric = pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
        values = []
        for value in series:
            if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                values.append(None)
            elif numeric:
                values.append(round(float(value), 9))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    return out


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    return frame.sort_values(by=list(frame.columns), na_position="last").reset_index(drop=True)


# (name, tree, defines-its-own-order, how many nodes should push)
CASES: list[tuple[str, Node, bool, int | None]] = [
    ("scan_only", SCAN, False, 1),
    (
        "filter",
        Filter(SCAN, Call("ge", (Column("amount"), Literal(100.0, FLOAT64)))),
        False,
        2,
    ),
    (
        "project",
        Project(SCAN, (("ident", Column("id")), ("shout", Call("upper", (Column("label"),))))),
        False,
        2,
    ),
    (
        "filter_then_aggregate",
        Aggregate(
            Filter(SCAN, Call("ge", (Column("amount"), Literal(50.0, FLOAT64)))),
            group_by=(("region", Column("region")),),
            aggregates=(("total", Call("sum", (Column("amount"),))),),
        ),
        False,
        3,
    ),
    (
        "full_pipeline",
        Limit(
            Sort(
                Aggregate(
                    Filter(SCAN, Call("ge", (Column("amount"), Literal(40.0, FLOAT64)))),
                    group_by=(("region", Column("region")),),
                    aggregates=(
                        ("total", Call("sum", (Column("amount"),))),
                        ("n", Call("count", (Column("id"),))),
                    ),
                ),
                keys=(SortKey(Column("total"), "desc"),),
            ),
            count=2,
        ),
        True,
        5,
    ),
    (
        "distinct",
        Distinct(Project(SCAN, (("region", Column("region")),))),
        False,
        3,
    ),
    (
        "case_expression",
        Project(
            SCAN,
            (
                ("id", Column("id")),
                (
                    "band",
                    Case(
                        ((Call("ge", (Column("amount"), Literal(100.0, FLOAT64))), Literal("big", STRING)),),
                        default=Literal("small", STRING),
                    ),
                ),
            ),
        ),
        False,
        2,
    ),
    (
        "nulls_in_predicate",
        Filter(SCAN, Call("is_not_null", (Column("region"),))),
        False,
        2,
    ),
    (
        "median_forces_a_local_aggregate",
        # sqlite has no MEDIAN lowering, so the aggregate and everything above
        # it must run here -- and still produce the same answer.
        Sort(
            Aggregate(
                SCAN,
                group_by=(("region", Column("region")),),
                aggregates=(("m", Call("median", (Column("amount"),))),),
            ),
            keys=(SortKey(Column("region"), "asc"),),
        ),
        True,
        1,
    ),
    (
        "extension_stops_the_prefix",
        Sort(
            Extension(
                Filter(SCAN, Call("ge", (Column("amount"), Literal(40.0, FLOAT64)))),
                "reverse_rows",
                (),
            ),
            keys=(SortKey(Column("id"), "asc"),),
        ),
        True,
        2,
    ),
]


@pytest.mark.parametrize(
    ("name", "tree", "ordered", "expected_pushed"),
    CASES,
    ids=[case[0] for case in CASES],
)
def test_planned_execution_equals_local_execution(
    name: str, tree: Node, ordered: bool, expected_pushed: int | None, db
) -> None:
    execution = plan(tree, "sqlite")

    if expected_pushed is not None:
        assert execution.pushed_count == expected_pushed, (
            f"{name}: expected {expected_pushed} node(s) pushed, got "
            f"{execution.pushed_count}\n" + execution.explain()
        )

    planned = _normalise(
        execute_plan(
            execution,
            run_sql=lambda sql: pd.read_sql_query(sql, db),
            frames={"orders": ORDERS},
        )
    )
    locally = _normalise(execute(tree, {"orders": ORDERS}))

    assert list(planned.columns) == list(locally.columns), (
        f"{name}: columns differ\n  planned={list(planned.columns)}\n"
        f"  local  ={list(locally.columns)}"
    )
    if not ordered:
        planned, locally = _sorted(planned), _sorted(locally)

    pd.testing.assert_frame_equal(
        planned, locally, check_dtype=False, obj=f"{name}\n{execution.explain()}"
    )


class TestTheSplitItself:
    def test_a_local_only_source_pushes_nothing(self) -> None:
        execution = plan(
            Filter(SCAN, Call("ge", (Column("amount"), Literal(1.0, FLOAT64)))),
            "local_files",
        )
        assert execution.fully_local
        assert execution.sql is None

    def test_an_unknown_source_is_treated_as_local(self) -> None:
        # The safe default: nothing is assumed to work.
        assert surface_for("some_new_connector").surface is Surface.NONE
        assert plan(SCAN, "some_new_connector").fully_local

    def test_every_local_node_says_why_it_stayed(self) -> None:
        # The most useful thing an optimiser can report is what stopped it.
        execution = plan(
            Sort(
                Aggregate(
                    SCAN,
                    group_by=(("region", Column("region")),),
                    aggregates=(("m", Call("median", (Column("amount"),))),),
                ),
                keys=(SortKey(Column("region"), "asc"),),
            ),
            "sqlite",
        )
        local = [d for d in execution.decisions if not d.pushed]
        assert local, "expected at least one local node"
        for decision in local:
            assert decision.reason.strip(), f"{decision.node} gave no reason"

    def test_the_reason_names_what_blocked_it(self) -> None:
        execution = plan(Extension(SCAN, "reverse_rows", ()), "sqlite")
        reasons = " ".join(d.reason for d in execution.decisions if not d.pushed)
        assert "extension" in reasons.lower()

    def test_nothing_above_a_local_step_is_pushed(self) -> None:
        # A step above a local step cannot run at the source: its input does not
        # exist there. Pushing it anyway would read the wrong rows.
        execution = plan(
            Limit(Extension(SCAN, "reverse_rows", ()), count=2),
            "sqlite",
        )
        assert execution.pushed_count == 1  # the scan only
        assert all(not d.pushed for d in execution.decisions[1:])

    def test_mysql_declares_what_it_cannot_do(self) -> None:
        surface = surface_for("mysql")
        assert surface.surface is Surface.SQL_LIMITED
        assert not surface.supports_set_ops
        assert surface.note

    def test_the_plan_reads_as_a_plan(self) -> None:
        execution = plan(
            Filter(SCAN, Call("ge", (Column("amount"), Literal(1.0, FLOAT64)))), "sqlite"
        )
        explained = execution.explain()
        assert "pushed to" in explained
        assert "SELECT" in explained


class TestItActuallyReducesWork:
    """The point of pushdown is moving fewer rows. Assert that, not just correctness.

    A planner that pushes everything and still transfers the whole table has
    achieved nothing; these measure what the source actually hands back.
    """

    def test_a_filter_transfers_only_matching_rows(self, db) -> None:
        tree = Filter(SCAN, Call("ge", (Column("amount"), Literal(200.0, FLOAT64))))
        execution = plan(tree, "sqlite")
        transferred = pd.read_sql_query(execution.sql, db)
        assert len(transferred) == 2, "the source should filter, not us"
        assert len(transferred) < len(ORDERS)

    def test_an_aggregate_transfers_groups_not_rows(self, db) -> None:
        # The single biggest win available: 8 rows become 4 groups. At a hundred
        # million rows this is the difference between working and not.
        tree = Aggregate(
            SCAN,
            group_by=(("region", Column("region")),),
            aggregates=(("total", Call("sum", (Column("amount"),))),),
        )
        execution = plan(tree, "sqlite")
        transferred = pd.read_sql_query(execution.sql, db)
        assert len(transferred) < len(ORDERS)

    def test_a_projection_transfers_only_the_columns_used(self, db) -> None:
        # Never SELECT * when two of four columns are needed.
        tree = Project(SCAN, (("id", Column("id")), ("amount", Column("amount"))))
        execution = plan(tree, "sqlite")
        transferred = pd.read_sql_query(execution.sql, db)
        assert list(transferred.columns) == ["id", "amount"]

    def test_a_limit_transfers_only_the_rows_asked_for(self, db) -> None:
        tree = Limit(Sort(SCAN, keys=(SortKey(Column("id"), "asc"),)), count=3)
        execution = plan(tree, "sqlite")
        transferred = pd.read_sql_query(execution.sql, db)
        assert len(transferred) == 3

    def test_a_local_only_source_transfers_everything(self, db) -> None:
        # Stated for contrast: this is what every pipeline did before the phase.
        execution = plan(
            Filter(SCAN, Call("ge", (Column("amount"), Literal(200.0, FLOAT64)))),
            "local_files",
        )
        assert execution.sql is None
        assert execution.fully_local



class TestPlanDescriptionFromRawRequests:
    """The preview receives plain dicts, not validated objects.

    A mock in the original unit test was an object, so `step.step_type` worked
    there and raised `AttributeError` against the real request body. These use
    the shapes the API actually sees.
    """

    def _dataset(self, source_type: str | None):
        class FakeSource:
            def __init__(self, value):
                self.source_type = value

        class FakeDataset:
            name = "orders"
            schema_json = {"ordered_columns": ["id", "region", "amount"]}
            source = FakeSource(source_type) if source_type else None

        return FakeDataset()

    def test_reads_steps_given_as_dicts(self) -> None:
        from service_transformations.preview import _describe_plan

        described = _describe_plan(
            self._dataset("postgresql"),
            [{"step_type": "limit_rows", "config": {"count": 5}}],
        )
        assert described is not None
        assert described.pushed_steps >= 1

    def test_reads_steps_given_as_objects(self) -> None:
        from service_transformations.preview import _describe_plan

        class Step:
            step_type = "limit_rows"
            config = {"count": 5}

        described = _describe_plan(self._dataset("postgresql"), [Step()])
        assert described is not None
        assert described.pushed_steps >= 1

    def test_a_stored_file_reports_that_nothing_pushes(self) -> None:
        # The honest and useful answer: this is why a pipeline over a hundred
        # million rows would be slow.
        from service_transformations.preview import _describe_plan

        described = _describe_plan(self._dataset(None), [])
        assert described is not None
        assert described.pushed_steps == 0
        assert described.sql is None

    def test_a_malformed_step_yields_no_plan_rather_than_a_wrong_one(self) -> None:
        from service_transformations.preview import _describe_plan

        assert _describe_plan(self._dataset("postgresql"), [{"config": {}}]) is None

    def test_an_unknown_step_type_yields_no_plan(self) -> None:
        from service_transformations.preview import _describe_plan

        described = _describe_plan(
            self._dataset("postgresql"), [{"step_type": "teleport", "config": {}}]
        )
        assert described is None


class TestDegenerateePlans:
    """The shapes that have no steps, or no pushdown, or neither."""

    def test_a_bare_scan_against_a_local_source_still_executes(self) -> None:
        # It crashed: with nothing pushed and no steps above it, the plan kept
        # no executable node at all and the executor was handed None.
        execution = plan(SCAN, "local_files")
        result = execute_plan(execution, frames={"orders": ORDERS})
        assert len(result) == len(ORDERS)

    def test_a_bare_scan_reports_no_steps_running_locally(self) -> None:
        # A scan is a read, not a step somebody added; counting it makes the
        # panel say "1 local" for an empty pipeline.
        assert plan(SCAN, "local_files").local_count == 0

    def test_a_local_pipeline_counts_only_its_steps(self) -> None:
        execution = plan(
            Filter(SCAN, Call("ge", (Column("amount"), Literal(1.0, FLOAT64)))),
            "local_files",
        )
        assert execution.local_count == 1

    def test_a_plan_that_pushes_still_needs_a_runner(self) -> None:
        # Refusing loudly beats silently running the pushed half locally and
        # reporting a number that came from somewhere else.
        execution = plan(SCAN, "sqlite")
        with pytest.raises(ValueError, match="no SQL runner"):
            execute_plan(execution, frames={"orders": ORDERS})

    def test_a_branching_tree_against_a_local_source_executes(self) -> None:
        other = Scan("regions", (("region", STRING), ("owner", STRING)))
        tree = Join(
            SCAN, other, on=Call("eq", (Column("region"), Column("region"))), how="inner"
        )
        execution = plan(tree, "local_files")
        result = execute_plan(
            execution,
            frames={
                "orders": ORDERS,
                "regions": pd.DataFrame({"region": ["eu"], "owner": ["ana"]}),
            },
        )
        assert len(result) == 3  # three eu rows

