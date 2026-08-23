"""Impact analysis: the three grades, and why the middle one matters most."""

from __future__ import annotations

from service_lineage.impact import (
    pipeline_impact,
    quality_rule_impact,
    rule_referenced_columns,
    secondary_input_impact,
    summarise,
    workflow_impact,
)

BASE = ["id", "region", "amount", "notes"]
DATASET = "55555555-5555-5555-5555-555555555555"


def _impact(steps, column, base=None):
    return pipeline_impact(
        pipeline_id="p1",
        pipeline_name="Clean orders",
        base_columns=base or BASE,
        steps=steps,
        targeted=[column],
    )


def test_a_column_named_by_a_step_breaks_the_pipeline():
    findings = _impact(
        [{"step_type": "filter_rows", "config": {"conditions": [{"column": "region", "operator": "equals", "value": "EU"}]}}],
        "region",
    )
    assert [finding.severity for finding in findings] == ["breaks"]
    assert "names 'region' directly" in findings[0].detail


def test_a_column_only_consumed_wholesale_changes_results_quietly():
    """The dangerous case: no error, different numbers."""
    findings = _impact([{"step_type": "remove_duplicates", "config": {}}], "notes")
    assert [finding.severity for finding in findings] == ["changes"]
    assert "without raising an error" in findings[0].detail


def test_a_configured_dedupe_subset_does_not_implicate_other_columns():
    """With a subset, dropping 'notes' no longer changes which rows survive.

    It still changes the output -- the column simply is not there any more --
    but that is the mild grade, not the silent-wrong-numbers one.
    """
    findings = _impact([{"step_type": "remove_duplicates", "config": {"subset": ["id"]}}], "notes")
    assert [finding.severity for finding in findings] == ["changes"]
    assert "which rows survive" not in findings[0].detail


def test_a_rename_stops_the_old_name_from_breaking_later_steps():
    """After a rename, later steps never see the original name."""
    steps = [
        {"step_type": "rename_columns", "config": {"mappings": {"region": "market"}}},
        {"step_type": "sort_rows", "config": {"columns": ["market"]}},
    ]
    findings = _impact(steps, "region")
    # Only the rename itself names it, not the sort three lines down.
    assert len(findings) == 1
    assert "Step 1" in findings[0].detail


def test_an_untouched_column_that_survives_to_the_output_is_a_change():
    findings = _impact([{"step_type": "limit_rows", "config": {"count": 5}}], "notes")
    assert [finding.severity for finding in findings] == ["changes"]
    assert "passes straight through" in findings[0].detail


def test_a_column_dropped_early_has_no_downstream_impact():
    steps = [
        {"step_type": "drop_columns", "config": {"columns": ["notes"]}},
        {"step_type": "sort_rows", "config": {"columns": ["amount"]}},
    ]
    findings = _impact(steps, "amount")
    assert [finding.severity for finding in findings] == ["breaks"]


def test_a_join_that_names_the_column_breaks():
    findings = secondary_input_impact(
        pipeline_id="p2",
        pipeline_name="Enrich",
        steps=[
            {
                "step_type": "join_datasets",
                "config": {
                    "right_dataset_id": DATASET,
                    "left_on": ["id"],
                    "right_on": ["customer_id"],
                    "select_right_columns": ["tier"],
                },
            }
        ],
        dataset_id=DATASET,
        targeted=["tier"],
    )
    assert [finding.severity for finding in findings] == ["breaks"]


def test_a_join_taking_every_column_changes_rather_than_breaks():
    findings = secondary_input_impact(
        pipeline_id="p2",
        pipeline_name="Enrich",
        steps=[
            {
                "step_type": "join_datasets",
                "config": {"right_dataset_id": DATASET, "left_on": ["id"], "right_on": ["id"]},
            }
        ],
        dataset_id=DATASET,
        targeted=["tier"],
    )
    assert [finding.severity for finding in findings] == ["changes"]


def test_a_strict_union_breaks_when_the_column_sets_stop_matching():
    findings = secondary_input_impact(
        pipeline_id="p3",
        pipeline_name="Combine",
        steps=[
            {
                "step_type": "union_datasets",
                "config": {"other_dataset_id": DATASET, "column_strategy": "strict"},
            }
        ],
        dataset_id=DATASET,
        targeted=["notes"],
    )
    assert [finding.severity for finding in findings] == ["breaks"]


def test_a_pipeline_on_another_dataset_is_not_implicated():
    findings = secondary_input_impact(
        pipeline_id="p4",
        pipeline_name="Unrelated",
        steps=[
            {
                "step_type": "join_datasets",
                "config": {"right_dataset_id": "00000000-0000-0000-0000-000000000000", "left_on": ["id"], "right_on": ["id"]},
            }
        ],
        dataset_id=DATASET,
        targeted=["notes"],
    )
    assert findings == []


def test_rule_columns_are_found_however_the_rule_spells_them():
    assert rule_referenced_columns({"column": "email"}) == {"email"}
    assert rule_referenced_columns({"columns": ["a", "b"]}) == {"a", "b"}
    assert rule_referenced_columns({"expression": "amount > discount"}) == {"amount", "discount"}
    assert rule_referenced_columns(None) == set()


def test_a_rule_on_the_column_always_breaks():
    finding = quality_rule_impact(
        rule_id="r1",
        rule_name="Email present",
        rule_type="not_null",
        severity="error",
        config={"column": "email"},
        targeted=["email"],
    )
    assert finding is not None
    assert finding.severity == "breaks"
    assert "quality gate fails" in finding.detail


def test_a_warning_rule_is_described_differently_from_a_gate():
    finding = quality_rule_impact(
        rule_id="r2",
        rule_name="Tidy notes",
        rule_type="pattern",
        severity="warning",
        config={"column": "notes"},
        targeted=["notes"],
    )
    assert finding is not None
    assert "reports an error instead of a result" in finding.detail


def test_a_rule_on_another_column_is_not_a_finding():
    assert (
        quality_rule_impact(
            rule_id="r3",
            rule_name="Other",
            rule_type="not_null",
            severity="error",
            config={"column": "id"},
            targeted=["email"],
        )
        is None
    )


def test_workflow_findings_name_the_nodes_involved():
    finding = workflow_impact(
        workflow_id="w1",
        workflow_name="Nightly",
        node_names=["extract", "validate", "publish", "notify"],
        targeted=["region"],
        reason="This workflow runs against the dataset",
    )
    assert finding.kind == "workflow"
    assert finding.detail.endswith("(extract, validate, publish…).")


def test_the_summary_leads_with_the_worst_outcome():
    breaks = _impact(
        [{"step_type": "sort_rows", "config": {"columns": ["region"]}}], "region"
    )
    assert "breaks" in summarise(breaks, ["region"])
    assert "safe to drop" in summarise([], ["region"])

    changes = _impact([{"step_type": "remove_duplicates", "config": {}}], "notes")
    assert "quietly produces different results" in summarise(changes, ["notes"])
