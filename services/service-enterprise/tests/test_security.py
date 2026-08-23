"""Row and column rules, and the ways they could leak."""

from __future__ import annotations

import pandas as pd

from service_enterprise.security import (
    ColumnRule,
    Policy,
    RowRule,
    apply_policies,
    effective_column_action,
    validate_policy,
)

FRAME = pd.DataFrame(
    {
        "region": ["north", "south", "north", "east"],
        "name": ["Ann", "Bo", "Cy", "Di"],
        "salary": [50000, 60000, 55000, 70000],
        "email": ["ann@x.com", "bo@y.com", "cy@z.com", "di@w.com"],
    }
)


def _policy(**overrides) -> Policy:
    base = {"name": "Regional", "role": "viewer"}
    base.update(overrides)
    return Policy(**base)


def test_no_policy_means_no_restriction():
    """A platform where nothing is readable until configured never gets finished."""
    frame, applied = apply_policies(FRAME, [], role="viewer")
    assert len(frame) == len(FRAME)
    assert applied.restricted is False
    assert applied.summary() == "You are seeing everything in this dataset."


def test_a_policy_for_another_role_does_not_apply():
    policy = _policy(row_rules=[RowRule("region", "equals", "north")])
    frame, applied = apply_policies(FRAME, [policy], role="admin")
    assert len(frame) == 4
    assert applied.policies_applied == []


def test_row_rules_hide_rows():
    policy = _policy(row_rules=[RowRule("region", "equals", "north")])
    frame, applied = apply_policies(FRAME, [policy], role="viewer")
    assert list(frame["region"]) == ["north", "north"]
    assert applied.rows_hidden == 2


def test_several_row_rules_narrow_further_rather_than_widening():
    policy = _policy(
        row_rules=[RowRule("region", "in", ["north", "south"]), RowRule("salary", "less_than", 56000)]
    )
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    assert sorted(frame["name"]) == ["Ann", "Cy"]


def test_a_denied_column_is_removed_entirely():
    policy = _policy(column_rules=[ColumnRule("salary", "deny")])
    frame, applied = apply_policies(FRAME, [policy], role="viewer")
    assert "salary" not in frame.columns
    assert applied.columns_removed == ["salary"]


def test_a_masked_column_keeps_its_rows_so_counts_still_work():
    """Masking and filtering are different things and must not be conflated."""
    policy = _policy(column_rules=[ColumnRule("email", "mask")])
    frame, applied = apply_policies(FRAME, [policy], role="viewer")
    assert len(frame) == len(FRAME)
    assert "email" in frame.columns
    assert applied.columns_masked == ["email"]
    assert all("@" in value for value in frame["email"])
    assert "ann@x.com" not in list(frame["email"])


def test_hashing_is_stable_so_masked_values_still_group():
    policy = _policy(column_rules=[ColumnRule("region", "hash")])
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    values = list(frame["region"])
    assert values[0] == values[2]  # both were 'north'
    assert values[0] != values[1]


def test_redaction_replaces_the_value_outright():
    policy = _policy(column_rules=[ColumnRule("name", "redact")])
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    assert set(frame["name"]) == {"[redacted]"}


def test_the_strictest_rule_wins_when_policies_disagree():
    """Otherwise adding a policy could widen access, which is backwards."""
    lenient = Policy(name="Lenient", role="viewer", column_rules=[ColumnRule("salary", "mask")])
    strict = Policy(name="Strict", role="viewer", column_rules=[ColumnRule("salary", "deny")])
    assert effective_column_action([lenient, strict], "salary") == "deny"
    assert effective_column_action([strict, lenient], "salary") == "deny"


def test_a_disabled_policy_restricts_nothing():
    policy = _policy(row_rules=[RowRule("region", "equals", "north")], enabled=False)
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    assert len(frame) == 4


def test_a_rule_naming_a_missing_column_hides_everything():
    """Failing open on a typo in a policy would be the worst possible default."""
    policy = _policy(row_rules=[RowRule("nonexistent", "equals", "x")])
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    assert len(frame) == 0


def test_null_handling_in_row_rules():
    frame = pd.DataFrame({"a": [1, None, 3]})
    kept, _applied = apply_policies(
        frame, [_policy(row_rules=[RowRule("a", "not_null")])], role="viewer"
    )
    assert len(kept) == 2


def test_a_non_numeric_comparison_hides_rather_than_raises():
    policy = _policy(row_rules=[RowRule("salary", "greater_than", "lots")])
    frame, _applied = apply_policies(FRAME, [policy], role="viewer")
    assert len(frame) == 0


def test_the_summary_says_what_was_restricted():
    policy = _policy(
        row_rules=[RowRule("region", "equals", "north")],
        column_rules=[ColumnRule("salary", "deny"), ColumnRule("email", "mask")],
    )
    _frame, applied = apply_policies(FRAME, [policy], role="viewer")
    summary = applied.summary()
    assert "2 row(s) hidden" in summary
    assert "1 column(s) masked" in summary
    assert "1 column(s) removed" in summary
    assert "Regional" in summary


def test_validation_catches_a_column_that_does_not_exist():
    problems = validate_policy(
        _policy(row_rules=[RowRule("ghost", "equals", 1)]), list(FRAME.columns)
    )
    assert any("would hide every row" in problem for problem in problems)


def test_validation_catches_an_operator_that_is_not_real():
    problems = validate_policy(
        _policy(row_rules=[RowRule("region", "roughly", "north")]), list(FRAME.columns)
    )
    assert any("not a row condition" in problem for problem in problems)


def test_validation_passes_a_sound_policy():
    assert (
        validate_policy(
            _policy(
                row_rules=[RowRule("region", "equals", "north")],
                column_rules=[ColumnRule("salary", "deny")],
            ),
            list(FRAME.columns),
        )
        == []
    )
