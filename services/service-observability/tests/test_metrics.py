"""Reading a time series out of a dataset profile."""

from __future__ import annotations

from service_observability.metrics import (
    COMPLETENESS,
    NULL_PERCENTAGE,
    ROW_COUNT,
    format_value,
    metrics_from_profile,
)

PROFILE = {
    "row_count": 1200,
    "column_count": 4,
    "duplicate_row_percentage": 1.5,
    "completeness_score": 98.25,
    "columns": [
        {"name": "id", "null_percentage": 0.0, "unique_count": 1200, "mean_value": 600.5},
        {"name": "email", "null_percentage": 7.0, "unique_count": 1180, "mean_value": None},
    ],
}


def _find(samples, key, column=None):
    return [s for s in samples if s.metric_key == key and s.column_name == column]


def test_dataset_wide_metrics_are_extracted():
    samples = metrics_from_profile(PROFILE)
    assert _find(samples, ROW_COUNT)[0].value == 1200.0
    assert _find(samples, COMPLETENESS)[0].value == 98.25


def test_per_column_metrics_carry_their_column_name():
    samples = metrics_from_profile(PROFILE)
    assert _find(samples, NULL_PERCENTAGE, "email")[0].value == 7.0


def test_a_null_column_statistic_is_skipped_rather_than_stored_as_zero():
    """Storing None as 0.0 would drag every baseline toward zero."""
    samples = metrics_from_profile(PROFILE)
    assert _find(samples, "mean_value", "email") == []


def test_nan_and_infinity_never_reach_the_history():
    profile = {"row_count": float("nan"), "column_count": float("inf"), "completeness_score": 90.0}
    keys = {sample.metric_key for sample in metrics_from_profile(profile)}
    assert keys == {"completeness_score"}


def test_booleans_are_not_treated_as_numbers():
    assert metrics_from_profile({"row_count": True}) == []


def test_a_missing_or_malformed_profile_yields_nothing():
    assert metrics_from_profile(None) == []
    assert metrics_from_profile({}) == []
    assert metrics_from_profile({"columns": ["not a dict"]}) == []


def test_wide_datasets_are_capped_so_one_profile_cannot_flood_the_table():
    profile = {
        "row_count": 10,
        "columns": [{"name": f"c{index}", "null_percentage": 0.0} for index in range(200)],
    }
    samples = metrics_from_profile(profile, max_columns=5)
    assert len({sample.column_name for sample in samples if sample.column_name}) == 5


def test_values_are_formatted_the_way_people_write_them():
    assert format_value(ROW_COUNT, 1200.0) == "1,200"
    assert format_value(COMPLETENESS, 98.25) == "98.2%"
    assert format_value("mean_value", 12.345) == "12.35"
