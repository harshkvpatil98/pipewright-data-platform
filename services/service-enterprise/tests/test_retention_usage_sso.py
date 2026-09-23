"""Retention, erasure, usage attribution, telemetry, and the SSO flow."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from service_enterprise.retention import (
    ErasureReport,
    ColumnHit,
    DeletionPlan,
    candidate_columns,
    cutoff_for,
    find_subject,
    redact_subject,
    resource_type_label,
)
from service_enterprise.saml import saml_status
from service_enterprise.sso import (
    ProviderConfig,
    build_authorization_request,
    discovery_url,
    generate_pkce,
    map_identity,
    normalise_username,
    verify_state,
)
from service_enterprise.telemetry import Metric, render
from service_enterprise.usage import UsageReport, UsageTotal
from shared_python.errors import BadRequestError, UnauthorizedError

PEOPLE = pd.DataFrame(
    {
        "customer_id": ["c1", "c2", "c3"],
        "email": ["ann@x.com", "bo@y.com", "ann@x.com"],
        "notes": ["first", "second", "third"],
    }
)


# ---- retention ----


def test_a_cutoff_is_the_retention_period_ago():
    now = datetime(2026, 3, 14, tzinfo=UTC)
    assert cutoff_for(30, now=now) == datetime(2026, 2, 12, tzinfo=UTC)


def test_a_dry_run_plan_says_nothing_was_deleted():
    plan = DeletionPlan("workflow_runs", cutoff_for(30), matched=42, dry_run=True)
    assert "Nothing was deleted" in plan.summary()
    assert plan.deleted == 0


def test_a_real_run_says_what_it_removed():
    plan = DeletionPlan("workflow_runs", cutoff_for(30), matched=42, dry_run=False, deleted=42)
    assert "Deleted 42" in plan.summary()


def test_an_empty_plan_says_there_was_nothing_to_do():
    plan = DeletionPlan("audit_entries", cutoff_for(30), matched=0, dry_run=False)
    assert "Nothing older than" in plan.summary()


def test_every_retainable_kind_has_a_readable_label():
    assert "workflow runs" in resource_type_label("workflow_runs").lower()


# ---- erasure ----


def test_candidate_columns_narrow_to_the_plausible_ones():
    assert candidate_columns(["email", "notes", "customer_id"], "email") == ["email"]
    assert candidate_columns(["phone_number", "notes"], "phone") == ["phone_number"]


def test_candidate_columns_fall_back_to_everything_when_nothing_matches():
    """Better a slow search than a search that quietly misses the person."""
    assert candidate_columns(["a", "b"], "email") == ["a", "b"]


def test_a_subject_is_found_wherever_they_appear():
    hits = find_subject(PEOPLE, "ann@x.com", ["email"])
    assert hits == [("email", 2)]


def test_a_subject_search_is_case_and_space_insensitive():
    assert find_subject(PEOPLE, "  ANN@X.COM ", ["email"]) == [("email", 2)]


def test_someone_absent_produces_no_hits():
    assert find_subject(PEOPLE, "nobody@z.com", ["email"]) == []


def test_redaction_replaces_the_value_and_keeps_the_rows():
    """Deleting rows would change every historical total computed from this."""
    redacted, affected = redact_subject(PEOPLE, "ann@x.com", ["email"])
    assert affected == 2
    assert len(redacted) == len(PEOPLE)
    assert list(redacted["email"]).count("[erased]") == 2
    assert list(redacted["notes"]) == ["first", "second", "third"]


def test_an_erasure_report_never_echoes_the_whole_subject_value():
    report = ErasureReport(subject_value="ann@example.com", subject_kind="email", datasets_searched=2)
    assert report.to_dict()["subject_value"] == "a***@example.com"


def test_an_erasure_report_says_where_the_person_was_found():
    report = ErasureReport(
        subject_value="ann@x.com",
        subject_kind="email",
        datasets_searched=3,
        hits=[ColumnHit("orders", "email", 4)],
    )
    assert "Found in 1 place(s) across 4 row(s)" in report.summary()
    assert "orders.email" in report.summary()


def test_an_erasure_report_for_somebody_absent_says_so_plainly():
    report = ErasureReport(subject_value="x@y.com", subject_kind="email", datasets_searched=5)
    assert "does not appear in any of them" in report.summary()


def test_unsearchable_datasets_are_reported_not_hidden():
    report = ErasureReport(
        subject_value="x@y.com", subject_kind="email", datasets_searched=1,
        unsearchable=["archive"],
    )
    assert "could not be searched" in report.summary()


# ---- usage ----


def test_usage_totals_convert_to_the_units_people_ask_in():
    total = UsageTotal("pipeline", None, "Nightly", runs=4, rows_processed=1000,
                       compute_ms=8500.0, bytes_written=2048)
    assert total.compute_seconds == 8.5
    assert total.average_rows_per_run == 250.0


def test_a_usage_report_names_the_biggest_consumer():
    report = UsageReport(period_days=30, since=datetime.now(UTC))
    report.totals = [
        UsageTotal("pipeline", None, "Nightly", 10, 9000, 1000.0, 0),
        UsageTotal("pipeline", None, "Hourly", 5, 1000, 500.0, 0),
    ]
    report.rows_processed = 10000
    report.compute_seconds = 1.5
    assert "'Nightly' accounts for 90% of the rows" in report.summary()


def test_an_empty_usage_report_says_nothing_ran():
    report = UsageReport(period_days=7, since=datetime.now(UTC))
    assert "Nothing has run in the last 7 day(s)" in report.summary()


# ---- telemetry ----


def test_metrics_render_as_valid_prometheus_text():
    output = render([Metric("projects_total", 4, "Projects that exist.")])
    assert "# HELP pipewright_projects_total Projects that exist." in output
    assert "# TYPE pipewright_projects_total gauge" in output
    assert "pipewright_projects_total 4" in output


def test_help_is_emitted_once_per_name_however_many_label_sets():
    """Repeating HELP is a parse error, and a failed scrape beats a missing metric."""
    output = render(
        [
            Metric("incidents_open", 1, "Open incidents.", labels=(("severity", "high"),)),
            Metric("incidents_open", 0, "Open incidents.", labels=(("severity", "low"),)),
        ]
    )
    assert output.count("# HELP pipewright_incidents_open") == 1
    assert 'pipewright_incidents_open{severity="high"} 1' in output


def test_label_values_are_escaped():
    output = render([Metric("thing", 1, "A thing.", labels=(("name", 'a"b'),))])
    assert '\\"' in output


def test_whole_numbers_render_without_a_decimal_point():
    assert "pipewright_thing 5\n" in render([Metric("thing", 5.0, "A thing.")])


# ---- sso ----


def _config(**overrides) -> ProviderConfig:
    base = {
        "issuer": "https://idp.example.com",
        "client_id": "pipewright",
        "client_secret": "secret",
        "redirect_uri": "https://app.example.com/callback",
        "authorization_endpoint": "https://idp.example.com/authorize",
    }
    base.update(overrides)
    return ProviderConfig(**base)


def test_pkce_produces_a_verifier_of_a_legal_length():
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43
    assert "=" not in verifier and "=" not in challenge


def test_two_pkce_pairs_are_never_the_same():
    assert generate_pkce()[0] != generate_pkce()[0]


def test_the_authorization_url_carries_pkce_and_a_nonce():
    request = build_authorization_request(_config())
    assert "code_challenge_method=S256" in request.url
    assert "nonce=" in request.url
    assert "response_type=code" in request.url


def test_the_verifier_never_reaches_a_response_body():
    """PKCE protects nothing if the verifier is handed to the browser."""
    request = build_authorization_request(_config())
    assert "code_verifier" not in request.to_dict()
    assert request.code_verifier not in str(request.to_dict())


def test_an_undiscovered_provider_cannot_produce_an_authorization_url():
    with pytest.raises(BadRequestError):
        build_authorization_request(_config(authorization_endpoint=None))


def test_a_callback_with_no_state_is_rejected():
    """Treating 'no state' as 'any state' is the attack this parameter stops."""
    with pytest.raises(UnauthorizedError):
        verify_state("expected", None)
    with pytest.raises(UnauthorizedError):
        verify_state(None, "received")


def test_a_mismatched_state_is_rejected():
    with pytest.raises(UnauthorizedError):
        verify_state("expected", "something-else")


def test_a_matching_state_passes():
    verify_state("abc", "abc")


def test_discovery_url_is_built_from_the_issuer():
    assert discovery_url("https://idp.example.com/") == (
        "https://idp.example.com/.well-known/openid-configuration"
    )


def test_claims_map_onto_a_user():
    identity = map_identity(
        {"sub": "abc", "email": "ann@x.com", "name": "Ann", "groups": ["analysts"]},
        _config(group_role_map={"analysts": "editor"}),
    )
    assert identity.subject == "abc"
    assert identity.username == "ann@x.com"
    assert identity.role == "editor"


def test_an_unmapped_group_falls_back_to_the_default_role():
    identity = map_identity({"sub": "abc", "groups": ["randoms"]}, _config(default_role="viewer"))
    assert identity.role == "viewer"


def test_a_token_with_no_subject_is_refused():
    """Without `sub` the same person becomes a new account on every email change."""
    with pytest.raises(UnauthorizedError):
        map_identity({"email": "ann@x.com"}, _config())


def test_a_single_group_sent_as_a_string_still_maps():
    identity = map_identity(
        {"sub": "abc", "groups": "admins"}, _config(group_role_map={"admins": "admin"})
    )
    assert identity.role == "admin"


def test_usernames_are_normalised_to_something_storable():
    assert normalise_username("  Ann O'Brien ") == "annobrien"
    assert normalise_username("!!!") == "sso-user"
    assert len(normalise_username("x" * 200)) == 80


def test_saml_is_off_until_a_provider_is_configured():
    """Implemented is not the same as available, and the status says which."""
    status = saml_status(None)
    assert status["implemented"] is True
    assert status["supported"] is False
    assert status["configured"] is False
    assert "no identity provider is configured" in status["reason"]
    assert "OIDC" in status["alternative"]
