"""The permission rule table.

This is the security boundary, so it is tested as one: not "does the happy path
work" but "is there a request that gets through when it should not".
"""

from __future__ import annotations

import pytest

from service_access.permissions import (
    ROLES,
    evaluate,
    highest,
    normalise_role,
    outranks,
    required_role,
)

PROJECT = "/api/v1/projects/11111111-1111-1111-1111-111111111111"


def test_roles_are_ordered_least_to_most_privileged():
    assert ROLES == ("viewer", "operator", "editor", "admin")
    assert outranks("admin", "viewer")
    assert not outranks("viewer", "operator")
    assert outranks("editor", "editor")


def test_an_unknown_role_never_outranks_anything():
    assert not outranks("superuser", "viewer")
    assert normalise_role("Nonsense") is None
    assert normalise_role(None) is None


def test_role_names_are_case_insensitive():
    assert normalise_role("Admin") == "admin"
    assert outranks("EDITOR", "operator")


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reads_need_only_membership(method):
    assert required_role(method, f"{PROJECT}/workflows") == "viewer"


def test_editing_a_definition_needs_an_editor():
    assert required_role("POST", f"{PROJECT}/workflows") == "editor"
    assert required_role("PATCH", f"{PROJECT}/pipelines/abc") == "editor"
    assert required_role("DELETE", f"{PROJECT}/datasets/abc") == "editor"


def test_running_something_needs_only_an_operator():
    assert required_role("POST", f"{PROJECT}/workflows/abc/run") == "operator"
    assert required_role("POST", f"{PROJECT}/workflows/abc/backfill") == "operator"
    assert required_role("POST", f"{PROJECT}/incidents/abc/resolve") == "operator"
    assert required_role("POST", f"{PROJECT}/freshness/check") == "operator"


def test_analytical_posts_are_reads_not_edits():
    """Asking a question must not require permission to change the answer."""
    assert required_role("POST", f"{PROJECT}/datasets/abc/impact") == "viewer"
    assert required_role("POST", f"{PROJECT}/datasets/abc/pipelines/preview") == "viewer"
    assert required_role("POST", f"{PROJECT}/workflows/abc/validate") == "viewer"


def test_managing_access_needs_an_admin():
    assert required_role("POST", f"{PROJECT}/members") == "admin"
    assert required_role("PATCH", f"{PROJECT}/members/abc") == "admin"
    assert required_role("DELETE", f"{PROJECT}/members/abc") == "admin"
    assert required_role("GET", f"{PROJECT}/members") == "admin"


def test_deleting_the_project_itself_needs_an_admin():
    assert required_role("DELETE", PROJECT) == "admin"
    # But deleting something *inside* it is ordinary editing.
    assert required_role("DELETE", f"{PROJECT}/workflows/abc") == "editor"


def test_member_management_wins_over_an_action_segment():
    """A path that is both must resolve to the stricter rule."""
    assert required_role("POST", f"{PROJECT}/members/abc/run") == "admin"


def test_an_unrecognised_write_path_fails_closed():
    assert required_role("POST", f"{PROJECT}/some-future-feature") == "editor"
    assert required_role("PUT", f"{PROJECT}/whatever/deeply/nested") == "editor"


def test_a_non_member_is_refused_whatever_they_ask_for():
    decision = evaluate(method="GET", path=f"{PROJECT}/workflows", role=None)
    assert decision.allowed is False
    assert "not a member" in decision.reason


def test_a_viewer_can_read_but_not_run():
    assert evaluate(method="GET", path=f"{PROJECT}/workflows", role="viewer").allowed
    denied = evaluate(method="POST", path=f"{PROJECT}/workflows/abc/run", role="viewer")
    assert denied.allowed is False
    assert denied.required_role == "operator"
    assert "you have viewer access" in denied.reason


def test_an_operator_can_run_but_not_edit():
    assert evaluate(method="POST", path=f"{PROJECT}/workflows/abc/run", role="operator").allowed
    assert not evaluate(method="POST", path=f"{PROJECT}/workflows", role="operator").allowed


def test_an_editor_can_edit_but_not_manage_access():
    assert evaluate(method="POST", path=f"{PROJECT}/workflows", role="editor").allowed
    assert not evaluate(method="POST", path=f"{PROJECT}/members", role="editor").allowed


def test_an_admin_can_do_everything():
    for method, path in [
        ("GET", f"{PROJECT}/workflows"),
        ("POST", f"{PROJECT}/workflows"),
        ("POST", f"{PROJECT}/workflows/abc/run"),
        ("POST", f"{PROJECT}/members"),
        ("DELETE", PROJECT),
    ]:
        assert evaluate(method=method, path=path, role="admin").allowed, (method, path)


def test_the_denial_message_names_what_is_missing():
    decision = evaluate(method="POST", path=f"{PROJECT}/members", role="viewer")
    assert "admin role or above" in decision.reason


def test_highest_picks_the_most_privileged_known_role():
    assert highest(["viewer", "admin", "operator"]) == "admin"
    assert highest(["viewer", "nonsense"]) == "viewer"
    assert highest(["nonsense", None]) is None
    assert highest([]) is None


def test_review_covers_definition_edits_only():
    """Gating runs behind review would stop on-call people doing their job."""
    from service_access.permissions import needs_review

    assert needs_review("POST", f"{PROJECT}/workflows")
    assert needs_review("PATCH", f"{PROJECT}/pipelines/abc")
    assert needs_review("DELETE", f"{PROJECT}/workflows/abc")

    assert not needs_review("GET", f"{PROJECT}/workflows")
    assert not needs_review("POST", f"{PROJECT}/workflows/abc/run")
    assert not needs_review("POST", f"{PROJECT}/workflows/abc/backfill")
    assert not needs_review("POST", f"{PROJECT}/incidents/abc/resolve")
    assert not needs_review("POST", f"{PROJECT}/datasets/abc/impact")
    assert not needs_review("POST", f"{PROJECT}/members")
    assert not needs_review("POST", f"{PROJECT}/data-quality/rules")


def test_applying_a_change_set_is_reviewable_but_staging_one_is_not():
    """In a governed project, the proposal is free and applying it is not.

    Gating the whole write-back surface would make it impossible to *prepare* a
    change for review, which is the thing review exists to receive.
    """
    from service_access.permissions import needs_review, review_refusal

    base = f"{PROJECT}/writeback/change-sets/abc"
    assert needs_review("POST", f"{base}/commit")
    assert not needs_review("POST", f"{PROJECT}/writeback/change-sets")
    assert not needs_review("POST", f"{base}/edits")
    assert not needs_review("POST", f"{base}/plan")
    assert not needs_review("POST", f"{base}/discard")
    assert not needs_review("GET", f"{base}/migration")

    # The refusal has to tell the truth about what to do next: the change set
    # already exists, so "propose it as a change request" is wrong advice.
    message = review_refusal("POST", f"{base}/commit")
    assert message is not None
    assert "review and commit" in message
    assert "Propose the edit" not in message


def test_the_default_review_message_still_applies_to_definitions():
    from service_access.permissions import review_refusal

    message = review_refusal("POST", f"{PROJECT}/workflows")
    assert message is not None
    assert "Propose the edit as a change request" in message
