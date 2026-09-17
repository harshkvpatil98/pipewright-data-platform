"""Path scopes, the enforced write boundary, and worktree separation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pw_dev.workspace.guard import PathGuard, PathViolation, normalise, resolve_within
from pw_dev.workspace.sandbox import build_profile, detect_sandbox_support, resolve_mode, sandbox_wrapper
from pw_dev.workspace.sentinel import Sentinel
from pw_dev.workspace.worktrees import WorktreeManager


# ------------------------------------------------------------------ path scope
@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    "../../../etc/passwd",
    "src/../../outside.py",
    "~/.ssh/id_rsa",
    "",
    "   ",
    ".",
    "a\x00b",
    "C:\\Windows\\System32",
])
def test_malicious_paths_are_refused(bad: str):
    with pytest.raises(PathViolation):
        normalise(bad)


def test_backslash_traversal_is_refused():
    with pytest.raises(PathViolation, match="traversal"):
        normalise("src\\..\\..\\outside.py")


@pytest.mark.parametrize("target", [
    ".git/config",
    ".git/hooks/pre-commit",
    ".pw-dev/state.sqlite3",
    "tools/dev-orchestrator/src/pw_dev/verify/registry.py",
    "tools/dev-orchestrator/src/pw_dev/publish/publisher.py",
    "tools/dev-orchestrator/pw-dev.toml",
    ".env",
    "apps/api-gateway/.env",
    ".github/workflows/ci.yml",
])
def test_controller_state_and_credentials_are_never_writable(target: str):
    """A task that can edit these can approve its own work."""
    guard = PathGuard(["**"])
    with pytest.raises(PathViolation):
        guard.check(target)


def test_a_task_cannot_widen_its_own_scope_by_declaring_a_forbidden_path():
    guard = PathGuard([".git/**", "src/**"])
    with pytest.raises(PathViolation, match="forbidden"):
        guard.check(".git/config")
    assert guard.check("src/app.py") == "src/app.py"


def test_a_path_outside_declared_ownership_is_refused():
    guard = PathGuard(["services/service-datasets/**"])
    with pytest.raises(PathViolation, match="outside this task's declared ownership"):
        guard.check("apps/web/app/page.tsx")


def test_directory_patterns_cover_their_subtree():
    guard = PathGuard(["services/service-datasets"])
    assert guard.check("services/service-datasets/src/models.py")
    with pytest.raises(PathViolation):
        guard.check("services/service-sources/src/models.py")


def test_double_star_crosses_directory_levels():
    guard = PathGuard(["apps/web/**"])
    assert guard.check("apps/web/app/projects/[id]/page.tsx")


def test_partition_separates_admissible_changes_from_violations():
    guard = PathGuard(["src/**"])
    ok, bad = guard.partition(["src/a.py", "src/b/c.py", "docs/x.md", "../escape.py"])
    assert ok == ["src/a.py", "src/b/c.py"]
    assert {v.path for v in bad} == {"docs/x.md", "../escape.py"}


def test_a_symlink_cannot_smuggle_a_write_out_of_the_tree(tmp_path: Path):
    root = tmp_path / "wt"
    (root / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "src" / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathViolation, match="outside"):
        resolve_within(root, "src/link/evil.py")


# -------------------------------------------------------------- the boundary
def test_the_host_reports_its_boundary_honestly():
    support = detect_sandbox_support(probe=True)
    assert support.mechanism
    assert support.detail
    if support.available:
        assert support.verified, "an available boundary must have been proved by probe"


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-specific")
def test_the_enforced_boundary_actually_denies_an_out_of_root_write(tmp_path: Path):
    """The claim this system rests on, tested rather than asserted.

    A worktree is not a boundary. This is.
    """
    support = detect_sandbox_support(probe=True)
    if not support.available:
        pytest.skip(f"this host cannot enforce writes: {support.detail}")

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    wrap = sandbox_wrapper([allowed], tmp_path / "profile.sb")
    assert wrap is not None

    inside = subprocess.run(  # noqa: S603
        wrap(["/bin/sh", "-c", f"echo ok > {allowed / 'f.txt'}"]),
        capture_output=True, text=True, check=False,
    )
    assert inside.returncode == 0, inside.stderr

    escape = subprocess.run(  # noqa: S603
        wrap(["/bin/sh", "-c", f"echo bad > {outside / 'f.txt'}"]),
        capture_output=True, text=True, check=False,
    )
    assert escape.returncode != 0
    assert not (outside / "f.txt").exists()

    neighbour = tmp_path / "other-worktree"
    neighbour.mkdir()
    cross = subprocess.run(  # noqa: S603
        wrap(["/bin/sh", "-c", f"echo bad > {neighbour / 'stolen.py'}"]),
        capture_output=True, text=True, check=False,
    )
    assert cross.returncode != 0, "a worker must not be able to write another worker's checkout"
    assert not (neighbour / "stolen.py").exists()


def test_a_profile_with_no_writable_root_is_refused():
    with pytest.raises(ValueError, match="cannot run a worker"):
        build_profile([])


def test_enforced_mode_is_refused_when_the_host_cannot_honour_it():
    from pw_dev.workspace.sandbox import SandboxSupport

    unavailable = SandboxSupport(False, "none", "no mechanism")
    with pytest.raises(RuntimeError, match="cannot enforce"):
        resolve_mode("enforced", unavailable)
    assert resolve_mode("auto", unavailable) == "supervised"
    assert resolve_mode("off", unavailable) == "off"


# -------------------------------------------------------------- tamper watch
def test_the_sentinel_notices_a_change_to_a_protected_file(tmp_path: Path):
    watched = tmp_path / "policy.toml"
    watched.write_text("mode = 'none'\n", encoding="utf-8")
    sentinel = Sentinel.capture(files=[watched], trees=[])
    assert sentinel.diff() == []

    watched.write_text("mode = 'feature_branch'\n", encoding="utf-8")
    changes = sentinel.diff()
    assert len(changes) == 1
    assert "contents changed" in changes[0]


def test_the_sentinel_notices_a_deletion_and_a_creation(tmp_path: Path):
    present = tmp_path / "a.txt"
    present.write_text("x", encoding="utf-8")
    absent = tmp_path / "b.txt"
    sentinel = Sentinel.capture(files=[present, absent], trees=[])
    present.unlink()
    absent.write_text("appeared", encoding="utf-8")
    changes = sentinel.diff()
    assert any("deleted" in c for c in changes)
    assert any("created where nothing existed" in c for c in changes)


# ---------------------------------------------------------------- worktrees
def test_each_task_gets_a_separate_checkout(fixture_repo: Path, tmp_path: Path):
    manager = WorktreeManager(fixture_repo, tmp_path / "run", "run-1")
    from pw_dev.workspace import git

    head = git.head_sha(fixture_repo)
    first = manager.create("T-01", base_commit=head)
    second = manager.create("T-02", base_commit=head)
    try:
        assert first.path != second.path
        assert (first.path / "src" / "app.py").exists()
        (first.path / "src" / "app.py").write_text("VALUE = 99\n", encoding="utf-8")
        assert (second.path / "src" / "app.py").read_text() == "VALUE = 1\n", (
            "one worker's edit must not appear in another's checkout"
        )
        assert (fixture_repo / "src" / "app.py").read_text() == "VALUE = 1\n", (
            "and must not appear in the original checkout"
        )
    finally:
        manager.cleanup()
        manager.prune_branches()


def test_a_worktree_in_the_user_s_source_tree_is_refused(fixture_repo: Path):
    from pw_dev.workspace.worktrees import Worktree

    manager = WorktreeManager(fixture_repo, fixture_repo / ".pw-dev" / "run", "run-1")

    with pytest.raises(Exception, match="the original checkout"):
        manager.verify_distinct(
            Worktree(task_id="T-01", path=fixture_repo, branch="b", base_commit="x")
        )
    with pytest.raises(Exception, match="would land in the user's tree"):
        manager.verify_distinct(
            Worktree(task_id="T-01", path=fixture_repo / "src", branch="b", base_commit="x")
        )
    # The run's own worktree directory is gitignored and excluded from every
    # fingerprint, so a checkout under it is legitimate.
    manager.verify_distinct(Worktree(
        task_id="T-01", path=manager.root / "T-01-a1", branch="b", base_commit="x",
    ))


def test_a_downstream_task_starts_from_its_prerequisite_not_the_base(fixture_repo: Path, tmp_path: Path):
    """Branching every task from the base is how two workers invent two contracts."""
    from pw_dev.workspace import git

    base = git.head_sha(fixture_repo)
    (fixture_repo / "src" / "contract.py").write_text("SCHEMA = 'v1'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fixture_repo, check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        ["git", "commit", "-q", "-m", "contract"], cwd=fixture_repo, check=True,
        capture_output=True,
        env={**__import__("os").environ, "GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@x.invalid",
             "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@x.invalid"},
    )
    after_contract = git.head_sha(fixture_repo)
    assert after_contract != base

    manager = WorktreeManager(fixture_repo, tmp_path / "run", "run-2")
    downstream = manager.create("T-02", base_commit=after_contract)
    try:
        assert (downstream.path / "src" / "contract.py").exists(), (
            "a dependent task must see its prerequisite's work"
        )
    finally:
        manager.cleanup()
        manager.prune_branches()
