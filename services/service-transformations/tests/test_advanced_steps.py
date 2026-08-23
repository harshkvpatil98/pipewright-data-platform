from __future__ import annotations

import uuid

import pandas as pd
import pytest

from service_transformations.executor import apply_transformation_steps
from service_transformations.schemas import TransformationStep
from service_transformations.steps import (
    apply_aggregate,
    apply_derive_column,
    apply_join_datasets,
    apply_limit_rows,
    apply_pivot,
    apply_replace_values,
    apply_sort_rows,
    apply_split_column,
    apply_union_datasets,
    apply_unpivot,
)
from service_transformations.steps.context import StepContext
from shared_python.errors import BadRequestError

RIGHT_ID = str(uuid.uuid4())


@pytest.fixture()
def sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["eu", "us", "eu", "apac"],
            "product": ["a", "a", "b", "b"],
            "amount": [10, 20, 30, 40],
            "customer_id": [1, 2, 1, 3],
        }
    )


@pytest.fixture()
def customers() -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2, 3], "customer_name": ["Alpha", "Beta", "Gamma"]})


def _context(frames: dict[str, pd.DataFrame]) -> StepContext:
    return StepContext(
        resolve_dataset=lambda dataset_id: frames[dataset_id].copy(),
        describe_dataset=lambda dataset_id: f"dataset-{dataset_id[:4]}",
    )


# --------------------------------------------------------------------- aggregate


def test_aggregate_groups_and_sums(sales: pd.DataFrame) -> None:
    result, _ = apply_aggregate(
        sales,
        {"group_by": ["region"], "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}]},
    )
    totals = dict(zip(result["region"], result["total"], strict=True))
    assert totals == {"apac": 40, "eu": 40, "us": 20}


def test_aggregate_supports_multiple_functions(sales: pd.DataFrame) -> None:
    result, _ = apply_aggregate(
        sales,
        {
            "group_by": ["region"],
            "aggregations": [
                {"column": "amount", "function": "sum", "alias": "total"},
                {"column": "amount", "function": "count", "alias": "orders"},
                {"column": "customer_id", "function": "count_distinct", "alias": "customers"},
            ],
        },
    )
    eu = result[result["region"] == "eu"].iloc[0]
    assert eu["total"] == 40
    assert eu["orders"] == 2
    assert eu["customers"] == 1


def test_aggregate_without_group_by_returns_single_row(sales: pd.DataFrame) -> None:
    result, warnings = apply_aggregate(
        sales, {"aggregations": [{"column": "amount", "function": "sum", "alias": "total"}]}
    )
    assert len(result) == 1
    assert result.iloc[0]["total"] == 100
    assert any("single summary row" in warning for warning in warnings)


def test_aggregate_rejects_duplicate_alias(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="Duplicate aggregation output name"):
        apply_aggregate(
            sales,
            {
                "group_by": ["region"],
                "aggregations": [
                    {"column": "amount", "function": "sum", "alias": "x"},
                    {"column": "amount", "function": "min", "alias": "x"},
                ],
            },
        )


def test_aggregate_rejects_alias_colliding_with_group_by(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="collide"):
        apply_aggregate(
            sales,
            {"group_by": ["region"], "aggregations": [{"column": "amount", "function": "sum", "alias": "region"}]},
        )


def test_aggregate_rejects_unknown_function(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="must be one of"):
        apply_aggregate(sales, {"aggregations": [{"column": "amount", "function": "kurtosis"}]})


# ------------------------------------------------------------------------- join


def test_join_enriches_with_right_columns(sales: pd.DataFrame, customers: pd.DataFrame) -> None:
    result, _ = apply_join_datasets(
        sales,
        {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["id"], "how": "left"},
        _context({RIGHT_ID: customers}),
    )
    assert "customer_name" in result.columns
    assert len(result) == 4
    assert result.loc[result["customer_id"] == 1, "customer_name"].tolist() == ["Alpha", "Alpha"]


def test_inner_join_drops_unmatched_and_warns(sales: pd.DataFrame) -> None:
    partial = pd.DataFrame({"id": [1], "customer_name": ["Alpha"]})
    result, warnings = apply_join_datasets(
        sales,
        {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["id"], "how": "inner"},
        _context({RIGHT_ID: partial}),
    )
    assert len(result) == 2
    assert any("dropped" in warning for warning in warnings)


def test_join_can_select_subset_of_right_columns(sales: pd.DataFrame, customers: pd.DataFrame) -> None:
    extended = customers.assign(secret="hidden")
    result, _ = apply_join_datasets(
        sales,
        {
            "right_dataset_id": RIGHT_ID,
            "left_on": ["customer_id"],
            "right_on": ["id"],
            "how": "left",
            "select_right_columns": ["customer_name"],
        },
        _context({RIGHT_ID: extended}),
    )
    assert "customer_name" in result.columns
    assert "secret" not in result.columns


def test_join_warns_on_many_to_many(sales: pd.DataFrame) -> None:
    dupes = pd.DataFrame({"id": [1, 1], "tag": ["x", "y"]})
    _, warnings = apply_join_datasets(
        sales,
        {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["id"], "how": "inner"},
        _context({RIGHT_ID: dupes}),
    )
    assert any("many-to-many" in warning for warning in warnings)


def test_join_rejects_mismatched_key_counts(sales: pd.DataFrame, customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="same number of columns"):
        apply_join_datasets(
            sales,
            {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["id", "customer_name"]},
            _context({RIGHT_ID: customers}),
        )


def test_join_rejects_unknown_right_column(sales: pd.DataFrame, customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="unknown column"):
        apply_join_datasets(
            sales,
            {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["nope"]},
            _context({RIGHT_ID: customers}),
        )


def test_join_without_context_gives_clear_error(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="not available in the current context"):
        apply_join_datasets(
            sales,
            {"right_dataset_id": RIGHT_ID, "left_on": ["customer_id"], "right_on": ["id"]},
            StepContext(),
        )


def test_join_rejects_non_uuid_dataset_id(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="valid dataset id"):
        apply_join_datasets(
            sales,
            {"right_dataset_id": "not-a-uuid", "left_on": ["customer_id"], "right_on": ["id"]},
            StepContext(),
        )


# ------------------------------------------------------------------------ union


def test_union_appends_rows(sales: pd.DataFrame) -> None:
    more = sales.head(1).copy()
    result, _ = apply_union_datasets(sales, {"other_dataset_id": RIGHT_ID}, _context({RIGHT_ID: more}))
    assert len(result) == 5


def test_union_can_deduplicate(sales: pd.DataFrame) -> None:
    result, warnings = apply_union_datasets(
        sales, {"other_dataset_id": RIGHT_ID, "deduplicate": True}, _context({RIGHT_ID: sales.copy()})
    )
    assert len(result) == 4
    assert any("duplicate" in warning for warning in warnings)


def test_union_strict_rejects_column_mismatch(sales: pd.DataFrame) -> None:
    other = pd.DataFrame({"totally": ["different"]})
    with pytest.raises(BadRequestError, match="do not match"):
        apply_union_datasets(
            sales, {"other_dataset_id": RIGHT_ID, "column_strategy": "strict"}, _context({RIGHT_ID: other})
        )


def test_union_intersect_keeps_shared_columns(sales: pd.DataFrame) -> None:
    other = pd.DataFrame({"region": ["latam"], "unrelated": [1]})
    result, warnings = apply_union_datasets(
        sales, {"other_dataset_id": RIGHT_ID, "column_strategy": "intersect"}, _context({RIGHT_ID: other})
    )
    assert list(result.columns) == ["region"]
    assert any("shared column" in warning for warning in warnings)


# ------------------------------------------------------------- reshape and misc


def test_pivot_fans_out_values(sales: pd.DataFrame) -> None:
    result, _ = apply_pivot(
        sales, {"index": ["region"], "columns": "product", "values": "amount", "aggregation": "sum"}
    )
    assert "a" in result.columns and "b" in result.columns
    eu = result[result["region"] == "eu"].iloc[0]
    assert eu["a"] == 10 and eu["b"] == 30


def test_pivot_rejects_high_cardinality() -> None:
    wide = pd.DataFrame({"i": range(300), "c": [f"col{n}" for n in range(300)], "v": range(300)})
    with pytest.raises(BadRequestError, match="pivot limit"):
        apply_pivot(wide, {"index": ["i"], "columns": "c", "values": "v"})


def test_unpivot_melts_value_columns() -> None:
    wide = pd.DataFrame({"region": ["eu"], "q1": [10], "q2": [20]})
    result, _ = apply_unpivot(
        wide,
        {"id_columns": ["region"], "value_columns": ["q1", "q2"], "variable_column_name": "quarter", "value_column_name": "amount"},
    )
    assert result["quarter"].tolist() == ["q1", "q2"]
    assert result["amount"].tolist() == [10, 20]


def test_unpivot_defaults_to_all_non_id_columns() -> None:
    wide = pd.DataFrame({"region": ["eu"], "q1": [10], "q2": [20]})
    result, _ = apply_unpivot(wide, {"id_columns": ["region"]})
    assert len(result) == 2


def test_sort_rows_multi_column(sales: pd.DataFrame) -> None:
    result, _ = apply_sort_rows(sales, {"columns": ["region", "amount"], "ascending": [True, False]})
    assert result["region"].tolist() == ["apac", "eu", "eu", "us"]
    assert result["amount"].tolist()[:3] == [40, 30, 10]


def test_sort_rows_rejects_mismatched_ascending(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="matching config.columns"):
        apply_sort_rows(sales, {"columns": ["region", "amount"], "ascending": [True]})


def test_limit_rows_with_offset(sales: pd.DataFrame) -> None:
    result, _ = apply_limit_rows(sales, {"count": 2, "offset": 1})
    assert result["amount"].tolist() == [20, 30]


def test_limit_rows_beyond_end_warns(sales: pd.DataFrame) -> None:
    result, warnings = apply_limit_rows(sales, {"count": 5, "offset": 99})
    assert result.empty
    assert any("beyond" in warning for warning in warnings)


def test_derive_column_adds_computed_values(sales: pd.DataFrame) -> None:
    result, _ = apply_derive_column(sales, {"target_column": "doubled", "expression": "amount * 2"})
    assert result["doubled"].tolist() == [20, 40, 60, 80]


def test_derive_column_refuses_silent_overwrite(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="already exists"):
        apply_derive_column(sales, {"target_column": "amount", "expression": "amount * 2"})


def test_derive_column_overwrite_when_explicit(sales: pd.DataFrame) -> None:
    result, _ = apply_derive_column(
        sales, {"target_column": "amount", "expression": "amount * 2", "overwrite": True}
    )
    assert result["amount"].tolist() == [20, 40, 60, 80]


def test_split_column_creates_parts() -> None:
    frame = pd.DataFrame({"full_name": ["Ada Lovelace", "Alan Turing"]})
    result, _ = apply_split_column(
        frame, {"column": "full_name", "delimiter": " ", "into": ["first", "last"], "drop_original": True}
    )
    assert result["first"].tolist() == ["Ada", "Alan"]
    assert result["last"].tolist() == ["Lovelace", "Turing"]
    assert "full_name" not in result.columns


def test_split_column_keeps_remainder_in_last_part() -> None:
    frame = pd.DataFrame({"path": ["a/b/c/d"]})
    result, _ = apply_split_column(frame, {"column": "path", "delimiter": "/", "into": ["head", "rest"]})
    assert result["head"].item() == "a"
    assert result["rest"].item() == "b/c/d"


def test_replace_values_literal() -> None:
    frame = pd.DataFrame({"status": ["ACTIVE", "inactive", "ACTIVE"]})
    result, _ = apply_replace_values(
        frame, {"column": "status", "replacements": [{"find": "ACTIVE", "replace_with": "active"}]}
    )
    assert result["status"].tolist() == ["active", "inactive", "active"]


def test_replace_values_regex() -> None:
    frame = pd.DataFrame({"phone": ["555-123-4567"]})
    result, _ = apply_replace_values(
        frame, {"column": "phone", "replacements": [{"find": r"\D", "replace_with": ""}], "use_regex": True}
    )
    assert result["phone"].item() == "5551234567"


def test_replace_values_rejects_invalid_regex() -> None:
    frame = pd.DataFrame({"x": ["a"]})
    with pytest.raises(BadRequestError, match="not a valid regular expression"):
        apply_replace_values(
            frame, {"column": "x", "replacements": [{"find": "([", "replace_with": ""}], "use_regex": True}
        )


# ----------------------------------------------------------------- integration


def test_multi_step_pipeline_runs_in_order(sales: pd.DataFrame, customers: pd.DataFrame) -> None:
    """Join, derive, aggregate, and sort composed into one pipeline."""
    steps = [
        {
            "step_type": "join_datasets",
            "config": {
                "right_dataset_id": RIGHT_ID,
                "left_on": ["customer_id"],
                "right_on": ["id"],
                "how": "left",
                "select_right_columns": ["customer_name"],
            },
        },
        {"step_type": "derive_column", "config": {"target_column": "with_tax", "expression": "round(amount * 1.2, 2)"}},
        {
            "step_type": "aggregate",
            "config": {
                "group_by": ["customer_name"],
                "aggregations": [{"column": "with_tax", "function": "sum", "alias": "total_with_tax"}],
            },
        },
        {"step_type": "sort_rows", "config": {"columns": ["total_with_tax"], "ascending": False}},
    ]

    result, _ = apply_transformation_steps(sales, steps, _context({RIGHT_ID: customers}))

    assert list(result.columns) == ["customer_name", "total_with_tax"]
    assert result["customer_name"].tolist() == ["Alpha", "Gamma", "Beta"]
    assert result["total_with_tax"].tolist() == [48.0, 48.0, 24.0]


def test_unsupported_step_type_is_rejected(sales: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="unsupported step_type"):
        apply_transformation_steps(sales, [{"step_type": "teleport", "config": {}}])


def test_apply_single_step_signature_stays_backward_compatible(sales: pd.DataFrame) -> None:
    """Existing single-frame steps still work without a context argument."""
    from service_transformations.executor import apply_single_step

    result, _ = apply_single_step(sales, TransformationStep(step_type="limit_rows", config={"count": 1}))
    assert len(result) == 1
