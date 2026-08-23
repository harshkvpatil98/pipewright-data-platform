"""Anomaly detection: the cases where a naive threshold gets it wrong."""

from __future__ import annotations

import pytest

from service_observability.anomaly import (
    MIN_HISTORY,
    detect_anomaly,
    severity_for,
)


def _verdict(value, history, metric_key="row_count", **kwargs):
    return detect_anomaly(metric_key=metric_key, value=value, history=history, **kwargs)


def test_a_steady_metric_with_a_normal_value_is_fine():
    verdict = _verdict(1010, [1000, 1005, 995, 1002, 998, 1001])
    assert verdict.status == "ok"
    assert verdict.baseline == pytest.approx(1001.5, abs=1)


def test_a_collapse_in_row_count_is_flagged():
    verdict = _verdict(120, [1000, 1005, 995, 1002, 998, 1001])
    assert verdict.is_anomalous
    assert verdict.direction == "below"
    assert "88% below" in verdict.explanation


def test_too_little_history_reports_no_baseline_rather_than_guessing():
    verdict = _verdict(500, [1000, 1000])
    assert verdict.status == "no_baseline"
    assert verdict.baseline is None
    assert str(MIN_HISTORY) in verdict.explanation


def test_exactly_the_minimum_history_is_enough():
    verdict = _verdict(1000, [1000] * MIN_HISTORY)
    assert verdict.status == "ok"


def test_one_past_outlier_does_not_hide_the_next_one():
    """A mean-and-stdev baseline fails this; a median-and-MAD one does not."""
    history = [1000, 1000, 1000, 1000, 1000, 50000]
    verdict = _verdict(100, history)
    assert verdict.is_anomalous


def test_a_perfectly_flat_metric_tolerates_a_trivial_move():
    verdict = _verdict(1001, [1000] * 8)
    assert verdict.status == "ok"
    assert "still is" in verdict.explanation


def test_a_perfectly_flat_metric_flags_a_real_move():
    verdict = _verdict(1400, [1000] * 8)
    assert verdict.is_anomalous
    assert "was exactly" in verdict.explanation


def test_a_flat_metric_at_zero_flags_any_appearance():
    """Null rate that has always been zero, suddenly is not."""
    verdict = _verdict(4.0, [0.0] * 8, metric_key="null_percentage")
    assert verdict.is_anomalous


def test_sensitivity_changes_where_the_line_sits():
    history = [100, 102, 98, 101, 99, 100, 103]
    value = 105  # a move of about 3.4 modified-z on this history
    assert _verdict(value, history, sensitivity="low").status == "ok"
    assert _verdict(value, history, sensitivity="medium").status == "ok"
    assert _verdict(value, history, sensitivity="high").is_anomalous


def test_an_unknown_sensitivity_falls_back_to_the_default():
    history = [100, 102, 98, 101, 99, 100]
    assert _verdict(400, history, sensitivity="nonsense").is_anomalous


def test_non_numeric_history_entries_are_ignored():
    verdict = _verdict(1000, [1000, None, "x", True, 1001, 999, 1002, 998])
    assert verdict.status == "ok"
    assert verdict.sample_size == 5


def test_explanations_name_the_column_when_there_is_one():
    verdict = _verdict(
        50.0, [1.0, 1.2, 0.9, 1.1, 1.0, 1.05], metric_key="null_percentage", column_name="email"
    )
    assert "null rate of 'email'" in verdict.explanation
    assert "%" in verdict.explanation


def test_severity_reflects_the_size_of_the_move_not_the_score():
    """A stable metric scores enormously for a small move; that is not critical."""
    steady = [100, 102, 98, 101, 99, 100]
    assert _verdict(115, steady, sensitivity="high").score > 8  # statistically extreme
    assert severity_for(_verdict(115, steady, sensitivity="high")) == "medium"
    assert severity_for(_verdict(150, steady)) == "high"
    assert severity_for(_verdict(100000, steady)) == "critical"
    assert severity_for(_verdict(100, [100] * 8)) == "low"


def test_a_collapse_is_as_critical_as_an_explosion():
    """Percentage change cannot say this: a drop maxes out at 100%."""
    steady = [1000, 1002, 998, 1001, 999, 1000]
    assert severity_for(_verdict(120, steady)) == "critical"
    assert severity_for(_verdict(0, steady)) == "critical"


def test_a_sign_flip_is_never_a_small_change():
    history = [50.0, 51.0, 49.0, 50.5, 49.5, 50.0]
    assert severity_for(_verdict(-50.0, history, metric_key="mean_value")) == "critical"


def test_a_metric_that_was_always_zero_is_high_not_critical():
    verdict = _verdict(4.0, [0.0] * 8, metric_key="null_percentage")
    assert severity_for(verdict) == "high"
