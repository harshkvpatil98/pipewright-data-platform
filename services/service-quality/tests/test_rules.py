from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from service_quality.engine import evaluate_rule, evaluate_ruleset
from shared_python.errors import BadRequestError


@pytest.fixture()
def customers() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "email": ["a@example.com", None, "c@example.com", "not-an-email"],
            "status": ["active", "active", "archived", "unknown"],
            "balance": [10.0, -5.0, 300.0, 20.0],
        }
    )


def _rule(rule_type: str, config: dict, *, severity: str = "error", name: str | None = None) -> dict:
    return {"rule_type": rule_type, "config": config, "severity": severity, "name": name or rule_type}


# ------------------------------------------------------------------- not_null


def test_not_null_flags_missing_values(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="not_null", config={"column": "email"})
    assert result.status == "failed"
    assert result.failed_rows == 1
    assert result.failure_rate == 25.0


def test_not_null_passes_when_complete(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="not_null", config={"column": "id"})
    assert result.status == "passed"
    assert result.failed_rows == 0


def test_rule_on_missing_column_is_rejected(customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="not present"):
        evaluate_rule(customers, rule_type="not_null", config={"column": "nope"})


# --------------------------------------------------------------------- unique


def test_unique_flags_every_member_of_a_duplicate_group() -> None:
    frame = pd.DataFrame({"id": [1, 1, 2, 3]})
    result = evaluate_rule(frame, rule_type="unique", config={"column": "id"})
    assert result.status == "failed"
    # Both rows of the colliding pair are flagged so quarantine removes the collision.
    assert result.failed_rows == 2


def test_unique_supports_composite_key() -> None:
    frame = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "y", "x"]})
    assert evaluate_rule(frame, rule_type="unique", config={"columns": ["a", "b"]}).status == "passed"


# ------------------------------------------------------------- allowed_values


def test_allowed_values_flags_unexpected(customers: pd.DataFrame) -> None:
    result = evaluate_rule(
        customers, rule_type="allowed_values", config={"column": "status", "allowed_values": ["active", "archived"]}
    )
    assert result.status == "failed"
    assert result.failed_rows == 1
    assert "unknown" in result.details["unexpected_values"]


def test_allowed_values_can_reject_nulls(customers: pd.DataFrame) -> None:
    result = evaluate_rule(
        customers,
        rule_type="allowed_values",
        config={"column": "email", "allowed_values": ["a@example.com"], "allow_null": False},
    )
    assert result.failed_rows == 3  # the null plus two non-matching values


# ---------------------------------------------------------------------- range


def test_range_flags_out_of_bounds(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="range", config={"column": "balance", "min": 0, "max": 100})
    assert result.status == "failed"
    assert result.failed_rows == 2  # -5.0 and 300.0


def test_range_treats_non_numeric_as_failure() -> None:
    frame = pd.DataFrame({"amount": ["10", "abc", "30"]})
    result = evaluate_rule(frame, rule_type="range", config={"column": "amount", "min": 0})
    assert result.failed_rows == 1


def test_range_requires_a_bound(customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="requires config.min"):
        evaluate_rule(customers, rule_type="range", config={"column": "balance"})


# ---------------------------------------------------------------- regex_match


def test_regex_match_flags_invalid_email(customers: pd.DataFrame) -> None:
    result = evaluate_rule(
        customers,
        rule_type="regex_match",
        config={"column": "email", "pattern": r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}"},
    )
    assert result.status == "failed"
    assert result.failed_rows == 1  # the null is allowed by default


def test_regex_match_rejects_bad_pattern(customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="not a valid regular expression"):
        evaluate_rule(customers, rule_type="regex_match", config={"column": "email", "pattern": "(["})


# ----------------------------------------------------------------- expression


def test_expression_rule_uses_the_safe_evaluator(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="expression", config={"expression": "balance >= 0"})
    assert result.status == "failed"
    assert result.failed_rows == 1


def test_expression_rule_passes_when_all_true(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="expression", config={"expression": "id > 0"})
    assert result.status == "passed"


def test_expression_rule_cannot_execute_arbitrary_code(customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError):
        evaluate_rule(customers, rule_type="expression", config={"expression": "__import__('os')"})


# ------------------------------------------------------- dataset-level checks


def test_row_count_below_minimum_fails(customers: pd.DataFrame) -> None:
    result = evaluate_rule(customers, rule_type="row_count", config={"min": 10})
    assert result.status == "failed"
    assert "at least 10" in result.message


def test_row_count_within_bounds_passes(customers: pd.DataFrame) -> None:
    assert evaluate_rule(customers, rule_type="row_count", config={"min": 1, "max": 10}).status == "passed"


def test_freshness_passes_for_recent_data() -> None:
    frame = pd.DataFrame({"updated_at": [datetime.now(UTC) - timedelta(hours=1)]})
    result = evaluate_rule(frame, rule_type="freshness", config={"column": "updated_at", "max_age_hours": 24})
    assert result.status == "passed"


def test_freshness_fails_for_stale_data() -> None:
    frame = pd.DataFrame({"updated_at": [datetime.now(UTC) - timedelta(days=10)]})
    result = evaluate_rule(frame, rule_type="freshness", config={"column": "updated_at", "max_age_hours": 24})
    assert result.status == "failed"
    assert result.details["age_hours"] > 24


def test_freshness_fails_when_unparseable() -> None:
    frame = pd.DataFrame({"updated_at": ["not a date"]})
    result = evaluate_rule(frame, rule_type="freshness", config={"column": "updated_at", "max_age_hours": 24})
    assert result.status == "failed"
    assert "no parseable timestamps" in result.message


def test_unknown_rule_type_is_rejected(customers: pd.DataFrame) -> None:
    with pytest.raises(BadRequestError, match="Unsupported rule type"):
        evaluate_rule(customers, rule_type="vibes", config={})


# --------------------------------------------------------------- the ruleset


def test_ruleset_reports_aggregate_status(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(
        customers,
        [
            _rule("not_null", {"column": "id"}),
            _rule("not_null", {"column": "email"}),
        ],
    )
    assert result.status == "failed"
    assert len(result.error_failures) == 1


def test_warning_severity_does_not_fail_the_ruleset(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(
        customers, [_rule("not_null", {"column": "email"}, severity="warning")]
    )
    assert result.status == "warning"
    assert result.error_failures == []
    assert len(result.warning_failures) == 1


def test_all_passing_ruleset_is_passed(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(customers, [_rule("not_null", {"column": "id"})])
    assert result.status == "passed"


def test_quarantine_splits_failing_rows(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(
        customers, [_rule("not_null", {"column": "email"})], quarantine=True
    )
    assert len(result.quarantined_frame) == 1
    assert len(result.passing_frame) == 3
    assert result.quarantined_frame.iloc[0]["id"] == 2


def test_quarantine_unions_failures_across_rules(customers: pd.DataFrame) -> None:
    """A row failing any error rule is quarantined once, not twice."""
    result = evaluate_ruleset(
        customers,
        [
            _rule("not_null", {"column": "email"}),
            _rule("range", {"column": "balance", "min": 0, "max": 100}),
        ],
        quarantine=True,
    )
    # id 2 fails both (null email, negative balance); id 3 fails the range only.
    assert sorted(result.quarantined_frame["id"].tolist()) == [2, 3]
    assert sorted(result.passing_frame["id"].tolist()) == [1, 4]


def test_warning_rules_do_not_quarantine(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(
        customers, [_rule("not_null", {"column": "email"}, severity="warning")], quarantine=True
    )
    assert result.quarantined_frame.empty
    assert len(result.passing_frame) == 4


def test_dataset_level_failure_warns_that_it_cannot_quarantine(customers: pd.DataFrame) -> None:
    result = evaluate_ruleset(customers, [_rule("row_count", {"min": 100})], quarantine=True)
    assert result.status == "failed"
    assert result.quarantined_frame.empty
    assert any("cannot be quarantined" in warning for warning in result.warnings)


def test_misconfigured_rule_is_recorded_not_raised(customers: pd.DataFrame) -> None:
    """One bad rule must not abort evaluation of the others."""
    result = evaluate_ruleset(
        customers,
        [
            _rule("not_null", {"column": "does_not_exist"}, name="broken"),
            _rule("not_null", {"column": "id"}, name="good"),
        ],
    )
    assert len(result.results) == 2
    broken = next(r for r in result.results if r.name == "broken")
    assert broken.evaluation.details.get("configuration_error") is True
    assert any("misconfigured" in warning for warning in result.warnings)
