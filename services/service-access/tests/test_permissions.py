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


def test_the_time_travel_role_matrix_is_the_intended_one():
    """Phase 18 §6: history and temporal reads are viewer; rewriting the head
    (rollback) or re-executing (replay) is editor. Pinned here so a route
    rename cannot silently change who may do what."""
    ds = f"{PROJECT}/datasets/abc"
    assert required_role("GET", f"{ds}/versions") == "viewer"
    assert required_role("GET", f"{ds}/versions/3") == "viewer"
    assert required_role("GET", f"{ds}/versions/3/preview") == "viewer"
    # A diff is a read whose parameters ride in the body.
    assert required_role("POST", f"{ds}/versions/diff") == "viewer"
    # Rollback publishes a new head; replay executes. Both are writes.
    assert required_role("POST", f"{ds}/versions/3/rollback") == "editor"
    # Replay lives under /runs, an operator segment; the explicit editor rule
    # must win over it, or replay would silently become an operator action.
    assert required_role("POST", f"{PROJECT}/runs/abc/replay") == "editor"
    # A temporal SQL query is a read that happens to POST (the SQL is the body);
    # it must not fall through to the write default.
    assert required_role("POST", f"{ds}/versions/query") == "viewer"


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


def test_changing_the_project_itself_needs_an_admin():
    """Renaming or archiving a project is administration, not editing.

    The project's own record says what the workspace is and whether it is still
    live; its pipelines and rules are what an editor edits. Both verbs are
    pinned because a rule written for one of them is a rule the other slips
    past -- `PUT` would otherwise fall through to the editor default.
    """
    assert required_role("PATCH", PROJECT) == "admin"
    assert required_role("PUT", PROJECT) == "admin"
    # And the contents stay editable by an editor, or this rule would lock
    # them out of the platform rather than out of one record.
    assert required_role("PATCH", f"{PROJECT}/pipelines/abc") == "editor"
    assert required_role("PATCH", f"{PROJECT}/datasets/abc") == "editor"


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


def test_the_workbench_reads_are_viewer_and_the_runs_are_operator():
    """Read-only by default, all the way up to the permission table.

    `explain` reports a plan without running anything, so it sits with the other
    analytical POSTs. `run` is operator because reaching into a source database
    is more than "see everything in the project" -- and a *write* needs admin,
    which the workbench service enforces on top of this.
    """
    base = f"{PROJECT}/workbench"
    assert required_role("POST", f"{base}/preview") == "viewer"
    assert required_role("POST", f"{base}/explain") == "viewer"
    assert required_role("GET", f"{base}/history") == "viewer"
    assert required_role("GET", f"{base}/schema/abc") == "viewer"
    assert required_role("POST", f"{base}/run") == "operator"
    assert required_role("POST", f"{base}/notebooks/abc/run") == "operator"
    assert required_role("POST", f"{base}/queries") == "editor"
    assert required_role("DELETE", f"{base}/queries/abc") == "editor"


def test_the_connector_schema_watch_is_an_operator_action():
    """Sweeping is running the nightly job by hand, not editing anything.

    It re-reads schemas and files drift incidents -- both things an operator
    does on call. Treating it as a definition change would put it behind the
    editor role and out of reach of the person who noticed the 3am failure.
    """
    assert required_role("GET", f"{PROJECT}/connectors/watch") == "viewer"
    assert required_role("POST", f"{PROJECT}/connectors/watch") == "operator"
    assert required_role("GET", f"{PROJECT}/connectors/usage") == "viewer"


def test_analysing_an_upload_is_a_read():
    """Working out how to read a file stores nothing.

    Requiring an editor for it would mean a viewer could not look at a file
    before somebody imports it, which is exactly when looking is useful. The
    import itself is still a write.
    """
    assert required_role("POST", f"{PROJECT}/datasets/analyze") == "viewer"
    assert required_role("POST", f"{PROJECT}/datasets/upload") == "editor"
    assert required_role("GET", f"{PROJECT}/ingest-specs") == "viewer"
    assert required_role("POST", f"{PROJECT}/ingest-specs") == "editor"
    assert required_role("DELETE", f"{PROJECT}/ingest-specs/abc") == "editor"
    # The chunked-upload endpoints are the ordinary upload, split up.
    assert required_role("POST", f"{PROJECT}/datasets/uploads") == "editor"
    assert required_role("PUT", f"{PROJECT}/datasets/uploads/abc/chunks/0") == "editor"
    assert required_role("POST", f"{PROJECT}/datasets/uploads/abc/complete") == "editor"
