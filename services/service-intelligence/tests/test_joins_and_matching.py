"""Join key detection and entity resolution."""

from __future__ import annotations

from service_intelligence.joins import (
    ColumnProfile,
    build_join_step,
    evaluate_pair,
    name_similarity,
    suggest_join_keys,
)
from service_intelligence.matching import (
    blocking_key,
    build_merge_step,
    find_duplicates,
    merge_plan,
    normalise,
    similarity,
)


# ---- joins ----


def test_the_real_join_is_found_and_nothing_else_is():
    orders = [
        ColumnProfile("order_id", ["o1", "o2", "o3"]),
        ColumnProfile("customer_id", ["c1", "c2", "c1"]),
        ColumnProfile("amount", [10, 20, 30]),
    ]
    customers = [
        ColumnProfile("id", ["c1", "c2", "c3"]),
        ColumnProfile("name", ["Ann", "Bo", "Cy"]),
    ]
    candidates = suggest_join_keys(orders, customers)
    assert [(c.left_column, c.right_column) for c in candidates] == [("customer_id", "id")]
    assert candidates[0].kind == "many_to_one"
    assert candidates[0].confidence == "high"


def test_a_key_stored_as_a_number_on_one_side_still_matches():
    """The single most common reason a join that should work returns nothing."""
    left = ColumnProfile("id", [1, 2, 3])
    right = ColumnProfile("id", ["1", "2", "3"])
    candidate = evaluate_pair(left, right)
    assert candidate is not None
    assert candidate.overlap == 1.0


def test_a_float_written_key_matches_its_integer_form():
    left = ColumnProfile("id", ["1.0", "2.0"])
    right = ColumnProfile("id", [1, 2])
    candidate = evaluate_pair(left, right)
    assert candidate is not None
    assert candidate.overlap == 1.0


def test_columns_sharing_no_values_are_not_a_join():
    assert evaluate_pair(ColumnProfile("a", ["x"]), ColumnProfile("b", ["y"])) is None


def test_a_matching_name_with_no_shared_values_is_still_not_a_join():
    """Name agreement is a tie-breaker, never evidence on its own."""
    assert (
        evaluate_pair(ColumnProfile("customer_id", ["a"]), ColumnProfile("customer_id", ["b"]))
        is None
    )


def test_a_many_to_many_join_is_warned_about():
    left = ColumnProfile("k", ["a", "a", "b"])
    right = ColumnProfile("k", ["a", "a", "b"])
    candidate = evaluate_pair(left, right)
    assert candidate is not None
    assert candidate.kind == "many_to_many"
    assert any("multiply" in warning for warning in candidate.warnings)


def test_a_partial_overlap_is_offered_with_a_warning_not_hidden():
    left = ColumnProfile("k", ["a", "b", "c", "d"])
    right = ColumnProfile("k", ["a", "z"])
    candidate = evaluate_pair(left, right)
    assert candidate is not None
    assert candidate.confidence == "low"
    assert any("would drop most rows" in warning for warning in candidate.warnings)


def test_name_similarity_ignores_naming_conventions():
    assert name_similarity("customer_id", "customerId") == 1.0
    assert name_similarity("customer_id", "CUSTOMER_ID") == 1.0
    assert name_similarity("customer_id", "id") == 0.5
    assert name_similarity("amount", "region") == 0.0


def test_the_suggestion_becomes_a_real_join_step():
    candidate = evaluate_pair(ColumnProfile("a", ["x"]), ColumnProfile("b", ["x"]))
    assert candidate is not None
    step = build_join_step(candidate, right_dataset_id="abc")
    assert step["step_type"] == "join_datasets"
    assert step["config"]["left_on"] == ["a"]
    assert step["config"]["right_on"] == ["b"]


# ---- matching ----


def test_company_suffixes_and_punctuation_are_not_identity():
    assert normalise("Acme Ltd") == normalise("ACME Limited") == normalise("Acme  Ltd.")


def test_the_same_words_in_a_different_order_are_the_same_thing():
    assert similarity(normalise("Smith John"), normalise("John Smith")) == 1.0


def test_blocking_puts_reordered_names_in_the_same_bucket():
    """A plain prefix would put them in different blocks and never compare them."""
    assert blocking_key(normalise("Smith John")) == blocking_key(normalise("John Smith"))


def test_values_identical_after_normalising_are_reported_not_silently_merged():
    report = find_duplicates(["Acme Ltd", "ACME Limited", "Acme  Ltd."], column="customer")
    assert len(report.candidates) == 2
    assert all(candidate.score == 1.0 for candidate in report.candidates)


def test_blocking_keeps_the_comparison_count_far_below_quadratic():
    values = [f"company {index}" for index in range(60)]
    report = find_duplicates(values, column="customer")
    naive = len(values) * (len(values) - 1) // 2
    assert report.comparisons < naive


def test_genuinely_different_values_are_not_matched():
    report = find_duplicates(["Initech", "Globex", "Umbrella"], column="customer")
    assert report.candidates == []
    assert "Nothing looks like a duplicate" in report.summary


def test_the_summary_says_nothing_was_merged():
    report = find_duplicates(["Acme Ltd", "Acme Limited"], column="customer")
    assert "Nothing has been merged" in report.summary


def test_a_merge_plan_keeps_the_longest_spelling():
    report = find_duplicates(["Acme Ltd", "Acme Limited"], column="customer")
    plan = merge_plan(report.candidates)
    assert plan == {"Acme Ltd": "Acme Limited"}


def test_the_merge_plan_becomes_a_replace_step():
    step = build_merge_step("customer", {"Acme Ltd": "Acme Limited"})
    assert step["step_type"] == "replace_values"
    assert step["config"]["column"] == "customer"


def test_empty_and_null_values_are_skipped():
    report = find_duplicates([None, "", "   ", "Acme"], column="customer")
    assert report.distinct_values == 1
