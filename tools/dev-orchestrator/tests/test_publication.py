"""Identity, attribution, and the publisher — against a real local bare remote."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pw_dev.config import PublicationPolicy
from pw_dev.publish.attribution import (clean_commit_message, scan_commit_metadata,
                                        scan_ref_name, scan_text)
from pw_dev.publish.identity import enforce_identity, inspect_identity, verify_identity
from pw_dev.publish.publisher import Publisher, PublicationRefusal
from pw_dev.util.hashing import tree_fingerprint
from pw_dev.workspace import git
from pw_dev.testing import run_git

OWNER = "harshkvpatil98"
EMAIL = "harshkvpatil@gmail.com"


def _policy(**overrides) -> PublicationPolicy:
    return PublicationPolicy(
        mode="feature_branch", remote="origin", branch_prefix="pw-dev",
        author_name=OWNER, author_email=EMAIL, **overrides,
    )


def _publisher(repo: Path, **overrides) -> Publisher:
    return Publisher(repo_root=repo, policy=_policy(**overrides), run_id="run-test-abcd1234")


def _change(repo: Path, text: str = "VALUE = 2\n") -> None:
    (repo / "src" / "app.py").write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ attribution
@pytest.mark.parametrize("text", [
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "Generated-by: Codex",
    "🤖 Generated with [Claude Code]",
    "Assisted-By: GPT-5",
    "feat: add snapshots (written by an AI)",
    "Signed-off-by: openai-bot[bot] <bot@openai.com>",
])
def test_assistant_attribution_in_commit_metadata_is_caught(text: str):
    assert scan_text(text, "subject"), f"{text!r} should be refused in commit metadata"


@pytest.mark.parametrize("text", [
    "feat: add time-travel snapshots",
    "Refactor the connector factory so tiers stay honest",
    "fix: SUM of an all-null group is NULL, not 0",
])
def test_ordinary_commit_messages_pass(text: str):
    assert scan_text(text, "subject") == []


def test_provider_names_in_source_code_are_not_authorship_claims():
    """`codex_cli.py` and `claude_cli.py` must keep their names.

    The scan is applied to commit metadata and ref names, never to a diff, so
    the technical identifiers this very repository needs are untouched.
    """
    diff_body = (
        "+from pw_dev.providers.claude_cli import ClaudeCliAdapter\n"
        "+# Drives `codex exec` for the planner role.\n"
        "+ANTHROPIC_DOCS = 'https://code.claude.com/docs/en/headless'\n"
    )
    # The publisher never calls scan_text on a diff; if it did, this would fire.
    assert scan_text(diff_body, "diff"), (
        "the pattern does match these strings — which is exactly why diffs are "
        "never scanned for attribution"
    )


def test_a_branch_name_naming_an_assistant_is_refused():
    assert scan_ref_name("claude/time-travel")
    assert scan_ref_name("codex-generated-fix")
    assert scan_ref_name("pw-dev/18-time-travel-abcd1234") == []


def test_a_composed_message_carrying_attribution_is_refused():
    with pytest.raises(ValueError, match="attribution"):
        clean_commit_message("feat: snapshots", "Co-Authored-By: Claude <x@y>")


def test_commit_metadata_scanning_covers_author_and_committer():
    findings = scan_commit_metadata(
        {"author_name": "Claude", "author_email": "noreply@anthropic.com",
         "committer_name": OWNER, "committer_email": EMAIL,
         "subject": "feat: x", "body": ""},
        sha="a" * 40,
    )
    assert len(findings) >= 2


# -------------------------------------------------------------------- identity
def test_identity_is_set_locally_and_verified(fixture_repo: Path):
    report = enforce_identity(fixture_repo, expected_name=OWNER, expected_email=EMAIL)
    assert report.ok
    assert git.out(fixture_repo, ["config", "--local", "--get", "user.name"]) == OWNER


def test_an_inherited_git_author_cannot_re_author_a_commit(fixture_repo: Path, monkeypatch):
    """The environment wins over configuration, so it is neutralised explicitly."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Someone Else")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "someone@else.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Another Person")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "another@person.invalid")

    report = inspect_identity(fixture_repo, expected_name=OWNER, expected_email=EMAIL)
    assert set(report.env_overrides) >= {"GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL"}

    _change(fixture_repo)
    publisher = _publisher(fixture_repo)
    base = git.head_sha(fixture_repo)
    fingerprint = tree_fingerprint(fixture_repo)
    sha, _, _ = publisher.commit(
        fixture_repo, base_commit=base, subject="feat: change", body="body",
        approved_fingerprint=fingerprint,
    )
    assert verify_identity(fixture_repo, sha, expected_name=OWNER, expected_email=EMAIL) == []
    metadata = git.commit_metadata(fixture_repo, sha)
    assert metadata["author_name"] == OWNER
    assert metadata["committer_name"] == OWNER


# ------------------------------------------------------------------- preflight
def test_a_candidate_that_changed_after_review_is_refused(fixture_repo: Path):
    """An approval of yesterday's diff cannot authorise today's commit."""
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)

    (fixture_repo / "src" / "sneaked_in.py").write_text("BACKDOOR = True\n", encoding="utf-8")

    publisher = _publisher(fixture_repo)
    checks = publisher.preflight(fixture_repo, base_commit=base, approved_fingerprint=approved)
    failed = [c for c in checks if not c.passed]
    assert failed and failed[0].name == "approved tree unchanged"
    assert "does not cover this tree" in failed[0].detail

    with pytest.raises(PublicationRefusal, match="approved tree unchanged"):
        publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                         approved_fingerprint=approved)


def test_worker_leftovers_are_refused(fixture_repo: Path):
    """A `.orig` or `.rej` is a worker's leftover, and it blocks."""
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    (fixture_repo / "notes.orig").write_text("x", encoding="utf-8")
    approved = tree_fingerprint(fixture_repo)

    checks = _publisher(fixture_repo).preflight(
        fixture_repo, base_commit=base, approved_fingerprint=approved,
    )
    junk = next(c for c in checks if c.name == "no temporary or build artefacts")
    assert not junk.passed
    assert "notes.orig" in junk.detail


def test_controller_state_and_check_debris_never_reach_the_index(fixture_repo: Path):
    """Running the checks is not a change to the tree being checked.

    `compileall` writes `__pycache__` into the candidate while verifying it, and
    the controller writes its own state under `.pw-dev/`. Neither is the
    worker's work, so neither is staged — and neither blocks publication for
    something the controller itself did.
    """
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    (fixture_repo / ".pw-dev").mkdir(exist_ok=True)
    (fixture_repo / ".pw-dev" / "state.sqlite3").write_text("x", encoding="utf-8")
    (fixture_repo / "src" / "__pycache__").mkdir(exist_ok=True)
    (fixture_repo / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00")
    approved = tree_fingerprint(fixture_repo)

    checks = _publisher(fixture_repo).preflight(
        fixture_repo, base_commit=base, approved_fingerprint=approved,
    )
    assert all(c.passed for c in checks), [c.detail for c in checks if not c.passed]

    sha, _, _ = _publisher(fixture_repo).commit(
        fixture_repo, base_commit=base, subject="feat: change", body="why",
        approved_fingerprint=approved,
    )
    published = git.out(fixture_repo, ["ls-tree", "-r", "--name-only", sha])
    assert ".pw-dev" not in published
    assert "__pycache__" not in published


def test_a_credential_in_the_diff_blocks_the_commit(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    (fixture_repo / "src" / "app.py").write_text(
        'API_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"\n', encoding="utf-8",
    )
    approved = tree_fingerprint(fixture_repo)
    checks = _publisher(fixture_repo).preflight(
        fixture_repo, base_commit=base, approved_fingerprint=approved,
    )
    secrets = next(c for c in checks if c.name == "no credential-shaped content in the diff")
    assert not secrets.passed
    assert "abcdefghijklmnop" not in secrets.detail, "the finding must not print the secret"


def test_a_change_outside_the_specification_scope_is_refused(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    (fixture_repo / "src" / "other.py").write_text("SNEAKED = 1\n", encoding="utf-8")
    approved = tree_fingerprint(fixture_repo)
    checks = _publisher(fixture_repo).preflight(
        fixture_repo, base_commit=base, approved_fingerprint=approved,
        allowed_paths=["src/app.py"],
    )
    scope = next(c for c in checks
                 if c.name == "changes are inside the specification's declared scope")
    assert not scope.passed
    assert "src/other.py" in scope.detail


def test_deletions_are_listed_for_review(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    (fixture_repo / "src" / "other.py").unlink()
    approved = tree_fingerprint(fixture_repo)
    checks = _publisher(fixture_repo).preflight(
        fixture_repo, base_commit=base, approved_fingerprint=approved,
    )
    deletions = next(c for c in checks if c.name == "deletions accounted for")
    assert "src/other.py" in deletions.detail


# ---------------------------------------------------------------------- commit
def test_the_committed_tree_is_exactly_the_approved_tree(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    sha, tree, checks = _publisher(fixture_repo).commit(
        fixture_repo, base_commit=base, subject="feat: change", body="why",
        approved_fingerprint=approved,
    )
    assert git.out(fixture_repo, ["rev-parse", f"{sha}^{{tree}}"]) == tree
    assert any(c.name == "committed tree equals the approved tree" and c.passed for c in checks)


def test_publication_produces_one_clean_commit_not_checkpoint_history(fixture_repo: Path):
    """Worker checkpoints stay local; nobody reads them on the published branch."""
    base = git.head_sha(fixture_repo)
    for index in range(3):
        _change(fixture_repo, f"VALUE = {index + 2}\n")
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", f"checkpoint: integrate T-0{index}")
    approved = tree_fingerprint(fixture_repo)

    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(
        fixture_repo, base_commit=base, subject="feat: change", body="why",
        approved_fingerprint=approved,
    )
    new_commits, problems = publisher.inspect_new_commits(
        fixture_repo, base_commit=base, head=sha,
    )
    assert problems == []
    assert len(new_commits) == 1, "the published branch carries one commit, not the checkpoints"
    assert "checkpoint" not in new_commits[0]["subject"]


def test_every_new_commit_is_inspected_including_pre_existing_bad_ones(fixture_repo: Path):
    """Metadata is read back from Git, for every commit, not just the one made here."""
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    run_git(fixture_repo, "add", "-A")
    run_git(
        fixture_repo, "commit", "-q", "-m",
        "checkpoint\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    )
    head = git.head_sha(fixture_repo)

    _, problems = _publisher(fixture_repo).inspect_new_commits(
        fixture_repo, base_commit=base, head=head,
    )
    assert problems, "an attributed commit reachable from the publication ref must be caught"
    assert any("co-authored-by" in p.lower() for p in problems)


def test_a_git_note_carrying_attribution_is_caught(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="feat: x",
                                 body="y", approved_fingerprint=approved)
    run_git(fixture_repo, "notes", "add", "-m", "Generated by Codex", sha)
    _, problems = publisher.inspect_new_commits(fixture_repo, base_commit=base, head=sha)
    assert any("note" in p.lower() for p in problems)


# ------------------------------------------------------------------------ push
def test_a_real_push_is_verified_by_reading_the_remote_ref_back(fixture_repo: Path, bare_remote: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="feat: x", body="y",
                                 approved_fingerprint=approved)
    branch = publisher.branch_name("18")
    result = publisher.push(fixture_repo, commit_sha=sha, branch=branch)

    assert result["remote_sha"] == sha
    assert any(c["name"] == "remote ref matches the intended commit" and c["passed"]
               for c in result["checks"])
    observed = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f"refs/heads/{branch}"], cwd=bare_remote,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert observed == sha


def test_pushing_to_a_protected_branch_is_refused(fixture_repo: Path, bare_remote: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                                 approved_fingerprint=approved)
    with pytest.raises(PublicationRefusal, match="protected branch"):
        publisher.push(fixture_repo, commit_sha=sha, branch="main")

    on_remote = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "refs/heads/main"], cwd=bare_remote,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert on_remote != sha, "main must be untouched"


def test_a_branch_that_moved_incompatibly_blocks_rather_than_being_overwritten(
    fixture_repo: Path, bare_remote: Path, tmp_path: Path,
):
    """Never force-push. The verified local result is preserved instead."""
    base = git.head_sha(fixture_repo)
    branch = "pw-dev/contested"

    # Somebody else publishes to the same branch first.
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", "-q", str(bare_remote), str(other)], check=True,  # noqa: S603
                   capture_output=True)
    (other / "theirs.txt").write_text("their work\n", encoding="utf-8")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-q", "-m", "their change")
    run_git(other, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    theirs = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f"refs/heads/{branch}"], cwd=bare_remote,
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo, allow_existing_branch=branch)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                                 approved_fingerprint=approved)
    with pytest.raises(PublicationRefusal, match="not an ancestor"):
        publisher.push(fixture_repo, commit_sha=sha, branch=branch)

    still_theirs = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f"refs/heads/{branch}"], cwd=bare_remote,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert still_theirs == theirs, "their work must not have been overwritten"


def test_a_failing_push_is_reported_not_swallowed(fixture_repo: Path, tmp_path: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    run_git(fixture_repo, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                                 approved_fingerprint=approved)
    with pytest.raises(PublicationRefusal):
        publisher.push(fixture_repo, commit_sha=sha, branch="pw-dev/x")


def test_a_missing_remote_is_refused(fixture_repo: Path):
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo)
    sha, _, _ = publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                                 approved_fingerprint=approved)
    with pytest.raises(PublicationRefusal, match="not configured"):
        publisher.push(fixture_repo, commit_sha=sha, branch="pw-dev/x")


def test_there_is_no_force_push_anywhere_in_the_publisher():
    """Grepped rather than asserted, so adding one later fails this test."""
    source = Path(__file__).resolve().parents[1] / "src" / "pw_dev" / "publish" / "publisher.py"
    body = source.read_text(encoding="utf-8")
    for forbidden in ("--force", "-f\"", "+refs/heads", "--force-with-lease"):
        assert forbidden not in body, f"{forbidden} appears in the publisher"


# --------------------------------------------------------------------- receipt
def test_the_receipt_reports_ci_honestly(fixture_repo: Path, bare_remote: Path):
    """A pushed branch does not run this repository's CI, and the receipt says so."""
    base = git.head_sha(fixture_repo)
    _change(fixture_repo)
    approved = tree_fingerprint(fixture_repo)
    publisher = _publisher(fixture_repo)
    sha, tree, checks = publisher.commit(fixture_repo, base_commit=base, subject="s", body="b",
                                         approved_fingerprint=approved)
    new_commits, _ = publisher.inspect_new_commits(fixture_repo, base_commit=base, head=sha)
    push = publisher.push(fixture_repo, commit_sha=sha, branch=publisher.branch_name("18"))

    receipt = publisher.receipt(
        published=True, base_commit=base, commit_sha=sha, tree_fingerprint_value=approved,
        approved_fingerprint=approved, branch=push["branch"], remote=push["remote"],
        remote_url=push["remote_url"], remote_sha=push["remote_sha"],
        new_commits=new_commits, checks=[c.to_dict() for c in checks],
        ci_status="not_triggered",
        notes=["this repository's CI runs on main/master and pull requests"],
    )
    assert receipt["ci_status"] == "not_triggered"
    assert receipt["identity"]["verified"]
    assert receipt["remote_sha_after_push"] == sha
    assert all(c["attribution_clean"] for c in receipt["new_commits"])


def test_signing_requirements_are_reported_not_disabled(fixture_repo: Path):
    run_git(fixture_repo, "config", "commit.gpgsign", "true")
    report = inspect_identity(fixture_repo, expected_name=OWNER, expected_email=EMAIL)
    assert report.signing_required
    assert any("will not be disabled" in p for p in report.problems)
