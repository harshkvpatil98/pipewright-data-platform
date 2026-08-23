"""The IR's validation contract.

Every rule here fires while a tree is being BUILT, not while it is running.
That is the point: a pipeline that cannot work should say so when someone
saves it, not at 3am when it is scheduled.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.types import (
    BOOLEAN,
    FLOAT64,
    INT32,
    INT64,
    Kind,
    STRING,
    decimal,
)
from service_transformations.ir.expressions import (
    FUNCTIONS,
    Call,
    Case,
    Cast,
    Column,
    Literal,
    is_aggregate,
)
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    IRError,
    Join,
    Limit,
    Project,
    Scan,
    SetOp,
    Sort,
    describe,
    freeze_config,
    pushable_to,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import Unsupported, can_compile, to_sql

SCAN = Scan("t", (("id", INT64), ("name", STRING), ("amount", decimal(18, 2))))
OTHER = Scan("u", (("id", INT64), ("owner", STRING)))


class TestProjectValidation:
    def test_rejects_an_empty_projection(self) -> None:
        with pytest.raises(IRError, match="at least one column"):
            Project(SCAN, ())

    def test_rejects_duplicate_output_names(self) -> None:
        # Two columns with one name means one of them is unreachable.
        with pytest.raises(IRError, match="Duplicate output"):
            Project(SCAN, (("a", Column("id")), ("a", Column("name"))))

    def test_rejects_a_missing_input_column(self) -> None:
        with pytest.raises(IRError, match="do not exist here"):
            Project(SCAN, (("a", Column("nope")),))

    def test_rejects_an_aggregate_in_a_projection(self) -> None:
        with pytest.raises(IRError, match="belongs in an Aggregate"):
            Project(SCAN, (("total", Call("sum", (Column("amount"),))),))

    def test_propagates_types_through_expressions(self) -> None:
        node = Project(SCAN, (("doubled", Call("mul", (Column("amount"), Literal(2, INT64)))),))
        assert node.schema()["doubled"].kind is Kind.DECIMAL


class TestFilterValidation:
    def test_requires_a_boolean_predicate(self) -> None:
        with pytest.raises(IRError, match="must be boolean"):
            Filter(SCAN, Column("amount"))

    def test_rejects_an_aggregate_predicate(self) -> None:
        with pytest.raises(IRError, match="cannot aggregate"):
            Filter(SCAN, Call("gt", (Call("sum", (Column("amount"),)), Literal(1, INT64))))

    def test_rejects_a_missing_column(self) -> None:
        with pytest.raises(IRError, match="do not exist here"):
            Filter(SCAN, Call("is_null", (Column("ghost"),)))

    def test_keeps_the_input_schema(self) -> None:
        node = Filter(SCAN, Call("is_not_null", (Column("id"),)))
        assert node.schema() == SCAN.schema()


class TestAggregateValidation:
    def test_requires_at_least_one_aggregate(self) -> None:
        with pytest.raises(IRError, match="at least one aggregate"):
            Aggregate(SCAN, group_by=(("name", Column("name")),), aggregates=())

    def test_rejects_a_non_aggregate_in_the_aggregates(self) -> None:
        with pytest.raises(IRError, match="does not aggregate"):
            Aggregate(SCAN, aggregates=(("x", Column("amount")),))

    def test_rejects_an_aggregate_as_a_grouping_key(self) -> None:
        with pytest.raises(IRError, match="cannot itself aggregate"):
            Aggregate(
                SCAN,
                group_by=(("k", Call("sum", (Column("amount"),))),),
                aggregates=(("n", Call("count", (Column("id"),))),),
            )

    def test_rejects_a_name_used_twice(self) -> None:
        with pytest.raises(IRError, match="Duplicate output"):
            Aggregate(
                SCAN,
                group_by=(("x", Column("name")),),
                aggregates=(("x", Call("count", (Column("id"),))),),
            )

    def test_sum_of_a_decimal_stays_exact(self) -> None:
        node = Aggregate(SCAN, aggregates=(("total", Call("sum", (Column("amount"),))),))
        assert node.schema()["total"].kind is Kind.DECIMAL

    def test_avg_becomes_a_float(self) -> None:
        node = Aggregate(SCAN, aggregates=(("mean", Call("avg", (Column("amount"),))),))
        assert node.schema()["mean"].kind is Kind.FLOAT64


class TestJoinValidation:
    def test_a_cross_join_takes_no_condition(self) -> None:
        with pytest.raises(IRError, match="no condition"):
            Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="cross")

    def test_every_other_join_needs_one(self) -> None:
        with pytest.raises(IRError, match="needs a condition"):
            Join(SCAN, OTHER, on=None, how="inner")

    def test_overlapping_names_are_suffixed_not_dropped(self) -> None:
        # Losing a column to a name clash is invisible until a report is wrong.
        node = Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="inner")
        assert "id" in node.schema()
        assert "id_right" in node.schema()

    def test_an_outer_join_makes_the_optional_side_nullable(self) -> None:
        node = Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="left")
        assert node.schema()["owner"].nullable

    def test_a_semi_join_contributes_no_right_columns(self) -> None:
        node = Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="semi")
        assert set(node.schema()) == set(SCAN.schema())


class TestOtherNodes:
    def test_sort_needs_a_key(self) -> None:
        with pytest.raises(IRError, match="at least one key"):
            Sort(SCAN, keys=())

    def test_limit_rejects_negatives(self) -> None:
        with pytest.raises(IRError, match="cannot be negative"):
            Limit(SCAN, count=-1)
        with pytest.raises(IRError, match="cannot be negative"):
            Limit(SCAN, offset=-1)

    def test_distinct_rejects_a_missing_column(self) -> None:
        with pytest.raises(IRError, match="do not exist here"):
            Distinct(SCAN, subset=("ghost",))

    def test_set_ops_require_matching_columns(self) -> None:
        with pytest.raises(IRError, match="same columns in the same order"):
            SetOp(SCAN, OTHER, kind="union")

    def test_set_ops_widen_column_types(self) -> None:
        left = Project(SCAN, (("v", Cast(Column("id"), INT64)),))
        right = Project(OTHER, (("v", Cast(Column("id"), FLOAT64)),))
        assert SetOp(left, right).schema()["v"].kind is Kind.FLOAT64

    def test_a_union_of_incompatible_types_is_unknown_not_a_guess(self) -> None:
        left = Project(SCAN, (("v", Cast(Column("id"), INT64)),))
        right = Project(OTHER, (("v", Cast(Column("owner"), STRING)),))
        assert SetOp(left, right).schema()["v"].kind is Kind.UNKNOWN

    def test_extension_reports_a_declared_schema(self) -> None:
        node = Extension(SCAN, "custom", (), output_schema=(("only", INT64),))
        assert node.schema() == {"only": INT64}

    def test_extension_without_a_declared_schema_passes_the_input_through(self) -> None:
        assert Extension(SCAN, "custom", ()).schema() == SCAN.schema()

    def test_extension_config_survives_freezing(self) -> None:
        # str() on the values turned ["a","b"] into "['a', 'b']" and broke the
        # step it was handed to.
        config = {"into": ["a", "b"], "opts": {"x": 1}, "n": 3}
        node = Extension(SCAN, "custom", freeze_config(config))
        assert node.config_dict() == config


class TestTreeWalking:
    def test_walk_yields_leaves_before_parents(self) -> None:
        tree = Limit(Filter(SCAN, Call("is_not_null", (Column("id"),))), count=1)
        assert [type(n).__name__ for n in tree.walk()] == ["Scan", "Filter", "Limit"]

    def test_describe_renders_the_tree(self) -> None:
        tree = Limit(SCAN, count=1)
        rendered = describe(tree)
        assert "Limit" in rendered and "Scan" in rendered
        assert rendered.index("Limit") < rendered.index("Scan")


class TestPushdown:
    def test_an_extension_never_pushes_down(self) -> None:
        # By construction: it is the escape hatch for things SQL cannot express.
        assert not pushable_to("postgres", Extension(SCAN, "custom", ()))

    def test_a_node_using_an_unsupported_function_does_not_push(self) -> None:
        node = Aggregate(SCAN, aggregates=(("m", Call("median", (Column("amount"),))),))
        assert not pushable_to("postgres", node)
        assert pushable_to("duckdb", node)

    def test_ordinary_nodes_push(self) -> None:
        node = Filter(SCAN, Call("gt", (Column("amount"), Literal(1, INT64))))
        assert pushable_to("postgres", node)


class TestExpressionContract:
    def test_an_unknown_function_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="Unknown function"):
            Call("teleport", (Column("id"),))

    @pytest.mark.parametrize(("name", "args"), [("upper", 0), ("eq", 1), ("between", 2)])
    def test_arity_is_checked(self, name: str, args: int) -> None:
        with pytest.raises(ValueError, match="takes"):
            Call(name, tuple(Column("id") for _ in range(args)))

    def test_columns_used_reaches_through_nesting(self) -> None:
        expr = Case(
            ((Call("gt", (Column("a"), Literal(1, INT64))), Call("upper", (Column("b"),))),),
            default=Cast(Column("c"), STRING),
        )
        assert expr.columns_used() == {"a", "b", "c"}

    def test_is_aggregate_reaches_through_nesting(self) -> None:
        assert is_aggregate(Cast(Call("sum", (Column("a"),)), STRING))
        assert is_aggregate(Case(((Literal(True, BOOLEAN), Call("max", (Column("a"),))),)))
        assert not is_aggregate(Call("upper", (Column("a"),)))

    def test_case_branches_that_cannot_meet_are_unknown(self) -> None:
        # Picking one arbitrarily would produce a column nobody can compute with.
        expr = Case(
            (
                (Literal(True, BOOLEAN), Literal(1, INT64)),
                (Literal(True, BOOLEAN), Literal("x", STRING)),
            )
        )
        assert expr.type_of({}).kind is Kind.UNKNOWN

    def test_an_unknown_column_types_as_unknown_rather_than_raising(self) -> None:
        assert Column("ghost").type_of({}).kind is Kind.UNKNOWN

    def test_every_declared_function_states_its_result_type(self) -> None:
        for name, signature in FUNCTIONS.items():
            args = [INT64] * max(signature.min_args, 1)
            assert signature.result_type(args) is not None, name

    def test_expressions_render_readably(self) -> None:
        expr = Call("upper", (Column("name"),))
        assert str(expr) == "upper(name)"
        assert str(Literal(None, STRING)) == "NULL"
        assert str(Cast(Column("id"), STRING)) == "cast(id as string)"


class TestSqlRefusals:
    """A dialect that cannot express something must say so, never approximate."""

    def test_an_extension_refuses(self) -> None:
        with pytest.raises(Unsupported, match="must run locally"):
            to_sql(Extension(SCAN, "custom", ()), "postgres")

    def test_a_missing_function_lowering_refuses(self) -> None:
        node = Aggregate(SCAN, aggregates=(("m", Call("median", (Column("amount"),))),))
        with pytest.raises(Unsupported, match="no lowering"):
            to_sql(node, "postgres")

    def test_mysql_refuses_intersect(self) -> None:
        left = Project(SCAN, (("v", Column("id")),))
        right = Project(OTHER, (("v", Column("id")),))
        with pytest.raises(Unsupported, match="does not support"):
            to_sql(SetOp(left, right, kind="intersect"), "mysql")

    def test_sqlite_refuses_a_full_outer_join(self) -> None:
        node = Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="full")
        with pytest.raises(Unsupported, match="FULL OUTER"):
            to_sql(node, "sqlite")

    def test_a_semi_join_refuses_rather_than_producing_a_wrong_join(self) -> None:
        node = Join(SCAN, OTHER, on=Call("eq", (Column("id"), Column("id"))), how="semi")
        assert not can_compile(node, "postgres")

    def test_an_unknown_dialect_is_an_error(self) -> None:
        with pytest.raises(Unsupported, match="No SQL dialect"):
            to_sql(SCAN, "teradata")

    def test_a_non_equality_join_condition_refuses(self) -> None:
        node = Join(
            SCAN, OTHER,
            on=Call("and", (Call("eq", (Column("id"), Column("id"))),
                            Call("is_null", (Column("name"),)))),
            how="inner",
        )
        with pytest.raises(Unsupported, match="comparisons combined with AND"):
            to_sql(node, "postgres")

    def test_identifiers_are_quoted_per_dialect(self) -> None:
        assert '"id"' in to_sql(SCAN, "postgres")
        assert "`id`" in to_sql(SCAN, "mysql")

    def test_an_identifier_containing_a_quote_is_escaped(self) -> None:
        # Not sanitisation theatre: a column named `we"ird` is legal in Postgres.
        odd = Scan("t", (('we"ird', INT64),))
        assert 'we""ird' in to_sql(odd, "postgres")

    def test_a_literal_containing_a_quote_is_escaped(self) -> None:
        node = Filter(SCAN, Call("eq", (Column("name"), Literal("O'Brien", STRING))))
        assert "O''Brien" in to_sql(node, "postgres")


class TestPandasRefusals:
    def test_a_missing_source_frame_is_reported_by_name(self) -> None:
        with pytest.raises(IRError, match="No frame supplied"):
            execute(SCAN, {})

    def test_an_unregistered_extension_is_reported(self) -> None:
        with pytest.raises(IRError, match="No handler registered"):
            execute(Extension(SCAN, "never_registered", ()), {"t": pd.DataFrame({"id": [1]})})


class TestArithmeticTyping:
    """Arithmetic is not widening, and conflating them typed real formulas as unknown.

    `widen` looks for a type that holds both values *exactly*, and correctly
    gives up on decimal-and-float because neither contains the other.
    Multiplying them is perfectly well defined: the inexact side wins.
    """

    @pytest.mark.parametrize(
        ("left", "right", "expected_kind"),
        [
            (decimal(18, 2), FLOAT64, Kind.FLOAT64),
            (FLOAT64, decimal(18, 2), Kind.FLOAT64),
            (decimal(18, 2), INT64, Kind.DECIMAL),
            (decimal(18, 2), decimal(10, 4), Kind.DECIMAL),
            (INT32, INT64, Kind.INT64),
            (INT64, FLOAT64, Kind.FLOAT64),
        ],
    )
    def test_result_type(self, left, right, expected_kind) -> None:
        node = Call("mul", (Column("a"), Column("b")))
        assert node.type_of({"a": left, "b": right}).kind is expected_kind

    def test_arithmetic_on_a_non_number_is_unknown_not_a_guess(self) -> None:
        node = Call("mul", (Column("a"), Column("b")))
        assert node.type_of({"a": STRING, "b": INT64}).kind is Kind.UNKNOWN

    def test_decimal_arithmetic_keeps_the_widest_shape(self) -> None:
        node = Call("mul", (Column("a"), Column("b")))
        result = node.type_of({"a": decimal(18, 2), "b": decimal(10, 4)})
        assert result.scale == 4

    def test_widen_still_refuses_the_pair_it_should(self) -> None:
        # The fix must not have loosened widening itself: there is genuinely no
        # exact common type for a decimal and a float.
        from shared_python.types import widen

        assert widen(decimal(18, 2), FLOAT64) is None

