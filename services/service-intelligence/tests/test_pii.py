"""PII detection, and the false positives that make it unusable."""

from __future__ import annotations

import pytest

from service_intelligence.pii import (
    DETECTORS_BY_KIND,
    MASKING_STRATEGIES,
    PiiFinding,
    masking_step,
    scan_column,
    scan_dataset,
)


def _kind(column: str, samples: list) -> str | None:
    finding = scan_column(column, samples)
    return finding.kind if finding else None


def test_emails_are_found_by_name_and_shape():
    finding = scan_column("email", ["a@x.com", "b@y.co.uk"])
    assert finding is not None
    assert finding.kind == "email"
    assert finding.confidence == "high"


def test_emails_are_found_even_when_the_column_is_called_something_else():
    finding = scan_column("contact_2", ["a@x.com", "b@y.co.uk", "c@z.org"])
    assert finding is not None
    assert finding.kind == "email"
    assert "whatever the column is called" in finding.reason


def test_a_name_match_with_no_matching_values_is_low_confidence():
    """A column called 'email' full of order ids is a coincidence, not PII."""
    finding = scan_column("email", ["1001", "1002", "1003"])
    assert finding is not None
    assert finding.confidence == "low"
    assert "probably a coincidence" in finding.reason


def test_a_card_number_is_a_card_not_a_phone():
    """Both patterns match sixteen digits; the checksum decides."""
    assert _kind("card_number", ["4111111111111111", "5500005555555559"]) == "credit_card"


def test_a_sixteen_digit_number_that_fails_the_checksum_is_not_a_card():
    finding = scan_column("reference", ["1234567890123456", "1111111111111111"])
    assert finding is None or finding.kind != "credit_card"


def test_an_order_id_is_not_an_ip_address():
    """The naive IPv6 pattern matched every digit string in the warehouse."""
    assert _kind("order_id", ["1001", "1002", "1003"]) is None


def test_a_version_string_is_not_a_phone_number():
    assert _kind("version", ["999.999.999.999", "1.2.3.4444"]) is None


def test_an_out_of_range_address_is_not_an_ip():
    assert _kind("code", ["999.999.999.999"]) is None


def test_a_real_ip_is_found():
    assert _kind("client_ip", ["192.168.1.4", "10.0.0.255"]) == "ip_address"


def test_names_are_flagged_from_the_column_name_at_medium_confidence():
    """Names have no pattern; saying so is better than pretending otherwise."""
    finding = scan_column("first_name", ["Ann", "Bo"])
    assert finding is not None
    assert finding.kind == "person_name"
    assert finding.confidence == "medium"
    assert "no pattern to check against" in finding.reason


def test_an_ordinary_text_column_is_not_flagged_at_all():
    assert scan_column("notes", ["hello", "world", "a longer note"]) is None


def test_an_empty_column_produces_nothing():
    assert scan_column("maybe_email", [None, "", "   "]) is None


def test_findings_come_back_most_confident_first():
    findings = scan_dataset(
        {
            "first_name": ["Ann", "Bo"],
            "email": ["a@x.com", "b@y.com"],
            "notes": ["hello"],
        }
    )
    assert [finding.kind for finding in findings] == ["email", "person_name"]


@pytest.mark.parametrize("kind", sorted(DETECTORS_BY_KIND))
def test_every_detector_proposes_a_workable_masking_step(kind: str):
    """A detector with no usable masking policy is a detector nobody can act on."""
    detector = DETECTORS_BY_KIND[kind]
    finding = PiiFinding(
        column="subject",
        kind=kind,
        label=detector.label,
        confidence="high",
        name_matched=True,
        value_match_rate=1.0,
        sample_size=10,
        suggested_strategy=detector.default_strategy,
        reason="fixture",
        guidance=detector.guidance,
    )
    step = masking_step(finding)
    assert step["step_type"] in {"drop_columns", "derive_column", "replace_values"}
    assert step["config"]
    assert detector.default_strategy in MASKING_STRATEGIES


def test_dropping_is_offered_as_a_strategy():
    finding = scan_column("email", ["a@x.com"])
    assert finding is not None
    assert masking_step(finding, strategy="drop") == {
        "step_type": "drop_columns",
        "config": {"columns": ["email"]},
    }


def test_partial_masking_of_an_email_keeps_the_domain():
    """Which is what analysis usually needs, and identifies nobody."""
    finding = scan_column("email", ["a@x.com"])
    assert finding is not None
    step = masking_step(finding, strategy="partial")
    assert step["config"]["column"] == "email"
    # The pattern targets everything before the @, leaving the domain intact.
    assert list(step["config"]["replacements"]) == ["^[^@]+"]


def test_an_unknown_strategy_is_refused():
    finding = scan_column("email", ["a@x.com"])
    assert finding is not None
    with pytest.raises(ValueError):
        masking_step(finding, strategy="obliterate")
