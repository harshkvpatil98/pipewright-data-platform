"""The one aggregation engine charts, pivots, and reports all share."""

from __future__ import annotations

import pandas as pd
import pytest

from service_reporting.aggregation import (
    Filter,
    Measure,
    Query,
    apply_filters,
    pivot,
    run_query,
)
from shared_python.errors import BadRequestError

FRAME = pd.DataFrame(
    {
        "region": ["north", "south", "north", "east", "south", "north"],
        "channel": ["web", "web", "store", "web", "store", "web"],
        "amount": [100, 250, 80, 120, 300, 50],
        "notes": ["a", None, "c", None, "e", "f"],
    }
)


def test_grouping_and_summing_gives_one_row_per_group():
    result = run_query(
        FRAME, Query(dimensions=["region"], measures=[Measure("amount", "sum", "total")])
    )
    totals = dict(zip(result.frame["region"], result.frame["total"], strict=True))
    assert totals == {"north": 230, "south": 550, "east": 120}


def test_results_are_sorted_by_the_measure_descending_by_default():
    """A chart nobody sorted is a chart nobody can read."""
    result = run_query(
        FRAME, Query(dimensions=["region"], measures=[Measure("amount", "sum", "total")])
    )
    assert list(result.frame["region"]) == ["south", "north", "east"]


def test_no_measure_means_count_which_is_what_was_being_asked():
    result = run_query(FRAME, Query(dimensions=["region"]))
    assert "count" in result.frame.columns
    assert result.frame["count"].sum() == len(FRAME)


def test_no_dimension_gives_one_row_of_totals_for_a_kpi():
    result = run_query(FRAME, Query(measures=[Measure("amount", "sum", "total")]))
    assert result.row_count == 1
    assert result.frame["total"].iloc[0] == 900


def test_several_measures_come_back_as_several_columns():
    result = run_query(
        FRAME,
        Query(
            dimensions=["region"],
            measures=[Measure("amount", "sum", "total"), Measure("amount", "max", "biggest")],
        ),
    )
    assert {"total", "biggest"} <= set(result.frame.columns)


def test_filters_narrow_before_aggregating():
    result = run_query(
        FRAME,
        Query(
            dimensions=["region"],
            measures=[Measure("amount", "sum", "total")],
            filters=[Filter("channel", "equals", "web")],
        ),
    )
    totals = dict(zip(result.frame["region"], result.frame["total"], strict=True))
    assert totals == {"north": 150, "south": 250, "east": 120}


@pytest.mark.parametrize(
    "operator,value,expected",
    [
        ("greater_than", 150, 2),
        ("greater_or_equal", 250, 2),
        ("less_than", 100, 2),
        ("not_equals", 100, 5),
        ("in", [100, 250], 2),
    ],
)
def test_every_comparison_filter_selects_what_it_says(operator, value, expected):
    assert len(apply_filters(FRAME, [Filter("amount", operator, value)])) == expected


def test_null_filters_find_the_gaps():
    assert len(apply_filters(FRAME, [Filter("notes", "is_null")])) == 2
    assert len(apply_filters(FRAME, [Filter("notes", "not_null")])) == 4


def test_contains_is_case_insensitive_because_people_are():
    assert len(apply_filters(FRAME, [Filter("region", "contains", "NORTH")])) == 3


def test_comparing_a_number_column_against_text_says_so():
    with pytest.raises(BadRequestError) as caught:
        apply_filters(FRAME, [Filter("amount", "greater_than", "lots")])
    assert "not a number" in str(caught.value.detail)


def test_an_unknown_filter_lists_the_ones_that_exist():
    with pytest.raises(BadRequestError) as caught:
        apply_filters(FRAME, [Filter("amount", "roughly", 100)])
    assert "contains" in str(caught.value.detail)


def test_filtering_everything_out_is_an_empty_result_not_an_error():
    result = run_query(
        FRAME,
        Query(
            dimensions=["region"],
            measures=[Measure("amount", "sum")],
            filters=[Filter("region", "equals", "atlantis")],
        ),
    )
    assert result.row_count == 0
    assert "Nothing matched the filters." in result.warnings


def test_summing_a_text_column_is_refused_rather_than_returning_nothing():
    with pytest.raises(BadRequestError) as caught:
        run_query(FRAME, Query(dimensions=["region"], measures=[Measure("channel", "sum")]))
    assert "no numeric values" in str(caught.value.detail)


def test_counting_a_text_column_is_fine():
    result = run_query(
        FRAME, Query(dimensions=["region"], measures=[Measure("channel", "count", "n")])
    )
    assert result.frame["n"].sum() == len(FRAME)


def test_count_distinct_counts_the_distinct_ones():
    result = run_query(FRAME, Query(measures=[Measure("region", "count_distinct", "regions")]))
    assert result.frame["regions"].iloc[0] == 3


def test_a_column_that_does_not_exist_names_itself():
    with pytest.raises(BadRequestError) as caught:
        run_query(FRAME, Query(dimensions=["planet"], measures=[Measure("amount", "sum")]))
    assert "planet" in str(caught.value.detail)


def test_grouping_by_too_many_columns_is_a_table_not_a_chart():
    with pytest.raises(BadRequestError) as caught:
        run_query(FRAME, Query(dimensions=["a", "b", "c", "d", "e"]))
    assert "at most" in str(caught.value.detail)


def test_the_limit_is_applied_and_reported():
    result = run_query(
        FRAME, Query(dimensions=["region"], measures=[Measure("amount", "sum")], limit=2)
    )
    assert result.row_count == 2
    assert result.truncated is True


def test_an_unknown_aggregation_lists_the_ones_that_exist():
    with pytest.raises(BadRequestError) as caught:
        run_query(FRAME, Query(dimensions=["region"], measures=[Measure("amount", "vibe")]))
    assert "median" in str(caught.value.detail)


# ---- pivot ----


def test_a_pivot_lays_one_measure_across_two_axes():
    result = pivot(FRAME, rows=["region"], columns=["channel"], measure=Measure("amount", "sum"))
    assert "region" in result.frame.columns
    assert {"web", "store"} <= set(result.frame.columns)


def test_a_pivot_needs_at_least_one_axis():
    with pytest.raises(BadRequestError) as caught:
        pivot(FRAME, rows=[], columns=[], measure=Measure("amount", "sum"))
    assert "at least one row or column" in str(caught.value.detail)


def test_a_pivot_refuses_a_column_field_with_too_many_values():
    """A hundred columns is not a pivot table, it is a wall."""
    wide = pd.DataFrame({"id": range(200), "key": [f"k{i}" for i in range(200)], "v": range(200)})
    with pytest.raises(BadRequestError) as caught:
        pivot(wide, rows=["id"], columns=["key"], measure=Measure("v", "sum"))
    assert "unreadable" in str(caught.value.detail)


def test_a_pivot_can_be_filtered_first():
    result = pivot(
        FRAME,
        rows=["region"],
        columns=["channel"],
        measure=Measure("amount", "sum"),
        filters=[Filter("channel", "equals", "web")],
    )
    assert "store" not in result.frame.columns
