"""Verification runs the phase's own code. This is what that code may touch.

The defect these pin down: every check ran with the controller's own write
access and the controller's own `HOME`. A `conftest.py` is imported by pytest
before the first test collects, and a task that legitimately owns a test file
legitimately owns that `conftest.py` — so "the candidate cannot run code during
verification" was never true, and defending the boundary by listing the
filenames that must not appear was always going to be incomplete.

Two halves, and both matter:

* the boundary **stops** what it claims to stop — the original checkout, its
  `.git`, the controller's run state, the operator's home;
* the boundary **does not** stop the checks the tool actually depends on. A
  confinement that made `npm run build` fail would be removed within a day, and
  rightly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pw_dev.verify import confine
from pw_dev.workspace.sandbox import already_sandboxed, detect_sandbox_support

REPO_ROOT = Path(__file__).resolve().parents[3]

needs_enforcement = pytest.mark.skipif(
    not detect_sandbox_support(probe=False).available or already_sandboxed(),
    reason=(
        "applying a sandbox requires a host that is not already inside one; "
        "Seatbelt profiles do not nest, and this suite runs as a confined check"
    ),
)


def _run_confined(boundary: confine.Confinement, script: str, *, cwd: Path) -> int:
    """Run a snippet through the boundary and report its exit status."""
    argv = boundary.apply([sys.executable, "-c", script])
    result = subprocess.run(  # noqa: S603 - fixed argv
        argv, cwd=cwd, capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "HOME": str(boundary.home)},
    )
    return result.returncode


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    target = tmp_path / "candidate"
    (target / "services").mkdir(parents=True)
    return target


@pytest.fixture
def original(tmp_path: Path) -> Path:
    target = tmp_path / "original"
    (target / "services").mkdir(parents=True)
    (target / "services" / "source.py").write_text("x = 1\n", encoding="utf-8")
    return target


# ------------------------------------------------------- what it stops
@needs_enforcement
def test_a_check_cannot_write_into_the_original_checkout(
        checkout: Path, original: Path, tmp_path: Path):
    """The tree being verified is writable. The tree it came from is not."""
    boundary = confine.for_check(
        "python:tests", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=original,
    )
    assert boundary.enforced

    mine = checkout / "services" / "written.py"
    theirs = original / "services" / "source.py"

    assert _run_confined(
        boundary, f"open({str(mine)!r}, 'w').write('ok')", cwd=checkout) == 0
    assert mine.exists(), "the checkout under test has to stay writable"

    assert _run_confined(
        boundary, f"open({str(theirs)!r}, 'w').write('changed')", cwd=checkout) != 0
    assert theirs.read_text(encoding="utf-8") == "x = 1\n"


@needs_enforcement
def test_a_check_cannot_write_the_controllers_run_state(
        checkout: Path, original: Path, tmp_path: Path):
    """Evidence, task states and approvals are the controller's, not a check's."""
    run_dir = tmp_path / "run"
    (run_dir / "evidence").mkdir(parents=True)
    ledger = run_dir / "evidence" / "recorded.json"
    ledger.write_text('{"outcome": "fail"}', encoding="utf-8")

    boundary = confine.for_check(
        "repo:verify", checkout=checkout, run_dir=run_dir,
        mode="enforced", repo_root=original,
    )
    assert _run_confined(
        boundary, f"open({str(ledger)!r}, 'w').write('{{}}')", cwd=checkout) != 0
    assert json.loads(ledger.read_text(encoding="utf-8"))["outcome"] == "fail"


@needs_enforcement
def test_a_check_cannot_write_another_worktree(
        checkout: Path, original: Path, tmp_path: Path):
    """A worker's checkout is not the candidate's to edit."""
    sibling = tmp_path / "worker-03"
    sibling.mkdir()
    owned = sibling / "theirs.py"
    owned.write_text("theirs = True\n", encoding="utf-8")

    boundary = confine.for_check(
        "python:tests", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=original,
    )
    assert _run_confined(
        boundary, f"open({str(owned)!r}, 'w').write('mine')", cwd=checkout) != 0
    assert owned.read_text(encoding="utf-8") == "theirs = True\n"


@needs_enforcement
def test_a_check_writing_to_home_writes_to_a_disposable_one(
        checkout: Path, original: Path, tmp_path: Path):
    """`~` exists, is writable, and is not the operator's."""
    boundary = confine.for_check(
        "web:build", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=original,
    )
    script = (
        "import os, pathlib;"
        "p = pathlib.Path(os.path.expanduser('~')) / '.npm' / 'marker';"
        "p.parent.mkdir(parents=True, exist_ok=True);"
        "p.write_text('cache')"
    )
    assert _run_confined(boundary, script, cwd=checkout) == 0
    assert (boundary.home / ".npm" / "marker").read_text(encoding="utf-8") == "cache"
    assert boundary.home != Path.home()


def test_each_check_gets_an_empty_home(checkout: Path, tmp_path: Path):
    """State one check leaves behind is not handed to the next one."""
    run_dir = tmp_path / "run"
    first = confine.for_check(
        "python:tests", checkout=checkout, run_dir=run_dir, mode="off")
    (first.home / "leftover").write_text("from the last check", encoding="utf-8")

    second = confine.for_check(
        "python:tests", checkout=checkout, run_dir=run_dir, mode="off")
    assert second.home == first.home
    assert not (second.home / "leftover").exists()


# ------------------------------------------------------- what it allows
@needs_enforcement
def test_a_check_may_write_its_own_scratch_and_caches(
        checkout: Path, original: Path, tmp_path: Path):
    """Build output, temp files and databases all live inside the checkout."""
    boundary = confine.for_check(
        "repo:verify", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=original,
    )
    script = (
        "import pathlib;"
        f"root = pathlib.Path({str(checkout)!r});"
        "(root / '.pw-dev-scratch' / 'tmp').mkdir(parents=True, exist_ok=True);"
        "(root / '.pw-dev-scratch' / 'tmp' / 'work').write_text('x');"
        "(root / 'apps' / 'web' / '.next').mkdir(parents=True, exist_ok=True);"
        "(root / 'apps' / 'web' / '.next' / 'build').write_text('y');"
        "(root / 'test.db').write_text('sqlite')"
    )
    assert _run_confined(boundary, script, cwd=checkout) == 0
    assert (checkout / "apps" / "web" / ".next" / "build").exists()
    assert (checkout / "test.db").exists()


# ------------------------------------------------------- shared trees
def test_a_copied_dependency_tree_needs_no_hole_in_the_original(
        checkout: Path, original: Path, tmp_path: Path):
    """The reason `node_modules` is copied rather than linked, stated as a test.

    A link would have to be followed on write, so the original directory would
    have to be granted. A real directory is already inside the checkout, so the
    boundary opens nothing.
    """
    (original / "node_modules").mkdir()
    (checkout / "node_modules").mkdir()
    assert confine.shared_cache_roots(checkout, original) == []

    boundary = confine.for_check(
        "web:build", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=original,
    )
    assert original not in boundary.write_roots
    assert not any(original in root.parents for root in boundary.write_roots)


def test_a_linked_dependency_tree_is_granted_and_nothing_else_is(
        checkout: Path, original: Path, tmp_path: Path):
    """A checkout that does borrow through a link gets that one directory."""
    (original / "node_modules").mkdir()
    (original / "secrets").mkdir()
    (checkout / "node_modules").symlink_to(original / "node_modules")

    granted = confine.shared_cache_roots(checkout, original)
    assert granted == [(original / "node_modules").resolve()]
    assert (original / "secrets").resolve() not in granted


def test_a_link_pointing_outside_the_original_is_not_granted(
        checkout: Path, original: Path, tmp_path: Path):
    """Only the repository's own directories, not wherever a link happens to go."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (checkout / "node_modules").symlink_to(elsewhere)
    assert confine.shared_cache_roots(checkout, original) == []


# ------------------------------------------------------- honesty
def test_confinement_that_could_not_be_applied_is_not_silently_skipped(
        checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Policy said confine. If it could not, the check has not run confined."""
    monkeypatch.setattr(confine, "sandbox_wrapper", lambda *a, **k: None)
    boundary = confine.for_check(
        "repo:verify", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced", repo_root=None,
    )
    assert boundary.failed
    assert not boundary.enforced


def test_the_report_states_what_the_boundary_does_not_cover(
        checkout: Path, tmp_path: Path):
    """`enforced` must not be read as more than writes."""
    boundary = confine.for_check(
        "repo:verify", checkout=checkout, run_dir=tmp_path / "run", mode="off")
    recorded = boundary.to_dict()
    assert recorded["covers"] == "file writes"
    assert "network" in recorded["does_not_cover"]


def test_a_check_id_with_a_colon_becomes_a_usable_directory_name():
    assert confine.slug("repo:live-acceptance") == "repo-live-acceptance"
    assert confine.slug("::") == "check"
