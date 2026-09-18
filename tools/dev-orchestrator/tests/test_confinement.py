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
        mode="enforced",
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
        mode="enforced",
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
        mode="enforced",
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
        mode="enforced",
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
        mode="enforced",
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


# ------------------------------------------------------- dependency trees
def test_a_dependency_tree_symlink_is_replaced_not_preserved(tmp_path: Path):
    """The escape the boundary would otherwise have handed back.

    `provide()` used to leave an existing entry alone, and the boundary used to
    grant the target of a `node_modules` symlink as a shared cache. Together
    that let a checkout point its own `node_modules` at the original repository
    and get write access to it during verification. Dependencies are copied
    now, and a link is not kept.
    """
    from pw_dev.workspace import node_modules

    repo = tmp_path / "repo"
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    (repo / "package.json").write_text('{"name": "r"}', encoding="utf-8")
    (repo / "secret.txt").write_text("not yours\n", encoding="utf-8")

    checkout = tmp_path / "candidate"
    checkout.mkdir()
    (checkout / "node_modules").symlink_to(repo)  # points at the whole repository

    node_modules.provide(repo, checkout)

    target = checkout / "node_modules"
    assert not target.is_symlink(), "a link must not survive into the checkout"
    assert target.is_dir()
    assert (target / "pkg").is_dir()
    assert not (target / "secret.txt").exists()


@needs_enforcement
def test_the_boundary_grants_nothing_outside_the_checkout_and_its_scratch(
        checkout: Path, tmp_path: Path):
    """Whatever the checkout contains, the grant is the checkout itself."""
    original = tmp_path / "original"
    (original / "node_modules").mkdir(parents=True)
    (checkout / "node_modules").symlink_to(original / "node_modules")

    boundary = confine.for_check(
        "web:build", checkout=checkout, run_dir=tmp_path / "run", mode="enforced")

    for root in boundary.write_roots:
        assert original not in root.parents and root != original, root


@needs_enforcement
def test_a_check_cannot_rewrite_the_interpreter_the_next_check_will_run(
        checkout: Path, tmp_path: Path):
    """`.venv` and `.git` are carved out of the grant on the checkout.

    Neither counts towards the tree fingerprint, so a check that replaced the
    interpreter would leave nothing for a later comparison to notice.
    """
    (checkout / ".venv" / "bin").mkdir(parents=True)
    interpreter = checkout / ".venv" / "bin" / "python"
    interpreter.write_text("#!/bin/sh\nexec /usr/bin/true\n", encoding="utf-8")
    (checkout / ".git").mkdir()
    head = checkout / ".git" / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")

    boundary = confine.for_check(
        "python:tests", checkout=checkout, run_dir=tmp_path / "run", mode="enforced")

    assert _run_confined(
        boundary, f"open({str(interpreter)!r}, 'w').write('replaced')",
        cwd=checkout) != 0
    assert "replaced" not in interpreter.read_text(encoding="utf-8")

    assert _run_confined(
        boundary, f"open({str(head)!r}, 'w').write('ref: refs/heads/other')",
        cwd=checkout) != 0
    assert head.read_text(encoding="utf-8") == "ref: refs/heads/main\n"


# ------------------------------------------------------- honesty
def test_confinement_that_could_not_be_applied_is_not_silently_skipped(
        checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Policy said confine. If it could not, the check has not run confined."""
    monkeypatch.setattr(confine, "sandbox_wrapper", lambda *a, **k: None)
    boundary = confine.for_check(
        "repo:verify", checkout=checkout, run_dir=tmp_path / "run",
        mode="enforced",
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
