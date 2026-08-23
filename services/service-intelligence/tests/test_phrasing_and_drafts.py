"""The phrase parser, explanation, rule suggestions, and generated drafts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from service_intelligence.documenting import (
    ColumnFacts,
    DatasetFacts,
    describe_column,
    describe_dataset,
)
from service_intelligence.explanation import TimelineEvent, describe_change, explain
from service_intelligence.phrasing import parse
from service_intelligence.rules import suggest_rules, summarise

COLUMNS = ["region", "channel", "amount", "notes", "customer_id"]


def _steps(sentence: str) -> list[dict]:
    return parse(sentence, COLUMNS).steps


# ---- phrase parsing ----


def test_a_grouped_total_becomes_an_aggregate_step():
    steps = _steps("total amount by region")
    assert steps == [
        {
            "step_type": "aggregate",
            "config": {
                "group_by": ["region"],
                "aggregations": [{"column": "amount", "function": "sum", "alias": "sum_amount"}],
            },
        }
    ]


def test_synonyms_for_the_same_aggregation_all_work():
    for phrase in ("total amount by region", "sum of amount by region", "add up amount per region"):
        assert _steps(phrase)[0]["config"]["aggregations"][0]["function"] == "sum"
    for phrase in ("average amount by region", "mean amount by region"):
        assert _steps(phrase)[0]["config"]["aggregations"][0]["function"] == "avg"


def test_a_filter_becomes_a_filter_step():
    steps = _steps("keep only rows where channel is web")
    assert steps[0]["config"]["conditions"] == [
        {"column": "channel", "operator": "equals", "value": "web"}
    ]


def test_several_conditions_become_several_conditions_not_one_swallowed_value():
    steps = _steps("where region is north and channel is web")
    assert len(steps[0]["config"]["conditions"]) == 2


def test_a_numeric_comparison_keeps_the_number_as_a_number():
    condition = _steps("keep only rows where amount over 100")[0]["config"]["conditions"][0]
    assert condition == {"column": "amount", "operator": "greater_than", "value": 100}


def test_exclude_inverts_the_comparison():
    condition = _steps("exclude rows where channel is store")[0]["config"]["conditions"][0]
    assert condition["operator"] == "not_equals"


def test_several_requests_in_one_sentence_become_several_steps():
    steps = _steps(
        "keep only rows where channel is web, then total amount by region, then sort by amount descending"
    )
    assert [step["step_type"] for step in steps] == [
        "filter_rows",
        "aggregate",
        "sort_rows",
    ]


def test_and_separates_requests_when_a_verb_follows_it():
    """'remove duplicates and drop notes' must not silently do only the first."""
    steps = _steps("remove duplicates and drop the notes column")
    assert [step["step_type"] for step in steps] == ["remove_duplicates", "drop_columns"]


def test_sorting_direction_is_read():
    assert _steps("sort by amount descending")[0]["config"]["ascending"] is False
    assert _steps("sort by amount")[0]["config"]["ascending"] is True


def test_renaming_is_understood():
    assert _steps("rename amount to revenue")[0]["config"]["mappings"] == {"amount": "revenue"}


def test_a_column_that_does_not_exist_says_which_ones_do():
    result = parse("total profit by region", COLUMNS)
    assert result.steps == []
    assert result.unknown_columns == ["profit"]
    assert "region, channel, amount" in result.summary


def test_a_partial_column_name_resolves_when_it_is_unambiguous():
    result = parse("total amount by customer", COLUMNS)
    assert result.steps[0]["config"]["group_by"] == ["customer_id"]


def test_something_it_cannot_read_is_reported_not_ignored():
    """A parser that quietly drops half a request is worse than one that says so."""
    result = parse("make it good", COLUMNS)
    assert result.steps == []
    assert result.complete is False
    assert "recognises phrases like" in result.summary


def test_a_partly_understood_sentence_says_what_was_left_out():
    result = parse("total amount by region, then do something clever", COLUMNS)
    assert len(result.steps) == 1
    assert result.not_understood == ["do something clever"]
    assert "left out rather than guessed at" in result.summary


def test_an_empty_sentence_is_handled():
    assert parse("   ", COLUMNS).summary == "Nothing to read."


# ---- explanation ----


NOW = datetime(2026, 3, 14, 9, 0, tzinfo=UTC)


def test_a_change_is_described_before_anything_explains_it():
    assert describe_change("row_count", 1000, 600) == (
        "row count fell 40%, from 1,000 to 600."
    )
    assert "rose" in describe_change("row_count", 100, 200)
    assert "first recorded" in describe_change("row_count", None, 50)
    assert "from zero" in describe_change("row_count", 0, 5)


def test_the_nearest_relevant_event_is_offered_first():
    events = [
        TimelineEvent("quality_failure", NOW - timedelta(days=1), "a rule failed"),
        TimelineEvent("pipeline_edit", NOW - timedelta(minutes=30), "filter changed"),
    ]
    report = explain(metric="row_count", changed_at=NOW, before=1000, after=600, events=events)
    assert report.candidates[0].kind == "pipeline_edit"
    assert "at the same time" in report.candidates[0].sentence


def test_events_outside_the_window_are_not_offered():
    events = [TimelineEvent("schema_drift", NOW - timedelta(days=10), "column removed")]
    report = explain(metric="row_count", changed_at=NOW, before=1000, after=600, events=events)
    assert report.candidates == []
    assert "upstream of anything this platform can see" in report.summary


def test_the_summary_says_what_changed_together_not_what_caused_what():
    """This is correlation, and saying otherwise would be a lie people act on."""
    events = [TimelineEvent("pipeline_edit", NOW, "filter changed")]
    report = explain(metric="row_count", changed_at=NOW, before=1000, after=600, events=events)
    assert "because" not in report.summary.lower()
    assert "caused" not in report.summary.lower()


def test_a_naive_timestamp_is_treated_as_utc():
    events = [TimelineEvent("pipeline_edit", datetime(2026, 3, 14, 9, 0), "edit")]
    report = explain(metric="row_count", changed_at=NOW, before=10, after=5, events=events)
    assert len(report.candidates) == 1


# ---- rule suggestions ----


PROFILE = {
    "row_count": 1200,
    "duplicate_row_count": 0,
    "columns": [
        {
            "name": "id",
            "inferred_type": "int",
            "null_count": 0,
            "unique_count": 1200,
            "possible_identifier": True,
        },
        {
            "name": "region",
            "inferred_type": "string",
            "null_count": 0,
            "unique_count": 4,
            "sample_values": ["north", "south", "east", "west"],
        },
        {
            "name": "amount",
            "inferred_type": "float",
            "null_count": 0,
            "unique_count": 900,
            "min_value": 0.5,
            "max_value": 999.0,
        },
        {"name": "notes", "inferred_type": "string", "null_count": 800, "unique_count": 300},
    ],
}


def test_a_never_null_column_is_suggested_as_not_null():
    kinds = {(item.rule_type, item.config.get("column")) for item in suggest_rules(PROFILE)}
    assert ("not_null", "id") in kinds
    assert ("not_null", "amount") in kinds


def test_a_mostly_empty_column_gets_no_not_null_rule():
    """A rule that fires constantly gets muted, and takes the real ones with it."""
    kinds = {(item.rule_type, item.config.get("column")) for item in suggest_rules(PROFILE)}
    assert ("not_null", "notes") not in kinds


def test_an_identifier_is_suggested_as_unique():
    assert any(
        item.rule_type == "unique" and item.config["column"] == "id"
        for item in suggest_rules(PROFILE)
    )


def test_a_low_cardinality_column_becomes_an_allowed_values_rule_at_medium_confidence():
    rule = next(item for item in suggest_rules(PROFILE) if item.rule_type == "allowed_values")
    assert rule.config["column"] == "region"
    # Medium, because the sample may not have seen every legitimate value.
    assert rule.confidence == "medium"


def test_a_never_negative_number_gets_a_range_rule():
    rule = next(item for item in suggest_rules(PROFILE) if item.rule_type == "range")
    assert rule.config == {"column": "amount", "min": 0}


def test_every_suggestion_explains_itself():
    assert all(len(item.rationale) > 20 for item in suggest_rules(PROFILE))


def test_a_tiny_dataset_produces_nothing_worth_asserting():
    tiny = {"row_count": 3, "duplicate_row_count": 0, "columns": [
        {"name": "a", "inferred_type": "string", "null_count": 0, "unique_count": 3}
    ]}
    assert not any(item.rule_type == "not_null" for item in suggest_rules(tiny))


def test_no_profile_produces_no_suggestions():
    assert suggest_rules(None) == []
    assert "nothing" in summarise([]).lower() or "Nothing" in summarise([])


# ---- documentation ----


def test_a_derived_dataset_says_where_it_came_from():
    draft = describe_dataset(
        DatasetFacts(
            name="orders_by_region",
            row_count=1240,
            column_count=4,
            is_derived=True,
            produced_by="Revenue by region",
            upstream_names=["orders"],
        )
    )
    assert "produced by the 'Revenue by region' pipeline from orders" in draft.text
    assert "1,240 rows across 4 columns" in draft.text
    assert "lineage" in draft.facts_used


def test_an_uploaded_dataset_says_that_instead():
    draft = describe_dataset(DatasetFacts(name="manual_upload"))
    assert "uploaded directly" in draft.text


def test_quality_problems_are_mentioned_when_there_are_any():
    draft = describe_dataset(
        DatasetFacts(name="messy", completeness=88.0, duplicate_percentage=4.0,
                     high_null_columns=["notes"])
    )
    assert "88.0% of cells are filled in" in draft.text
    assert "`notes` are mostly empty" in draft.text or "`notes` is mostly empty" in draft.text


def test_a_clean_dataset_gets_no_quality_complaint():
    draft = describe_dataset(DatasetFacts(name="clean", completeness=100.0, duplicate_percentage=0.0))
    assert "filled in" not in draft.text


def test_a_column_draft_covers_type_nulls_and_examples():
    draft = describe_column(
        ColumnFacts(
            name="email",
            inferred_type="string",
            null_percentage=7.0,
            sample_values=["a@x.com"],
            pii_kind="email",
        )
    )
    assert "Holds text" in draft.text
    assert "Missing in 7% of rows" in draft.text
    assert "personal data (email)" in draft.text
    assert "For example: 'a@x.com'" in draft.text


def test_a_column_with_nothing_recorded_says_so_rather_than_inventing():
    draft = describe_column(ColumnFacts(name="mystery"))
    assert "Nothing is recorded" in draft.text


def test_a_low_cardinality_column_is_described_as_a_category():
    draft = describe_column(ColumnFacts(name="region", unique_count=4, row_count=1000))
    assert "reads as a category" in draft.text


def test_uniqueness_is_not_suggested_from_a_handful_of_rows():
    """In eight rows every amount is distinct, and that means nothing."""
    tiny = {
        "row_count": 8,
        "duplicate_row_count": 0,
        "columns": [
            {
                "name": "amount",
                "inferred_type": "float",
                "null_count": 0,
                "unique_count": 8,
                "possible_identifier": True,
                "min_value": 600,
                "max_value": 3200,
            }
        ],
    }
    assert not any(item.rule_type == "unique" for item in suggest_rules(tiny))


def test_uniqueness_is_suggested_once_there_are_enough_rows():
    big = {
        "row_count": 5000,
        "duplicate_row_count": 0,
        "columns": [
            {
                "name": "id",
                "inferred_type": "int",
                "null_count": 0,
                "unique_count": 5000,
                "possible_identifier": True,
            }
        ],
    }
    rule = next(item for item in suggest_rules(big) if item.rule_type == "unique")
    assert "All 5,000 rows" in rule.rationale
