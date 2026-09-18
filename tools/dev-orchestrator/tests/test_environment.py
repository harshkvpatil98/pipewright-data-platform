"""A checkout gets an environment that imports *that* checkout's code.

The defect these pin down: a git worktree has no `.venv`, so every check
declaring `requires=("venv",)` recorded `not_run` and a run could never close
its completion gate. The tempting fix — symlink the original `.venv` — makes the
checks run and makes all of them verify the *original* checkout, because that is
where `pip install -e` points. A pass against code nobody is publishing is worse
than an honest `not_run`.

Two kinds of fixture here, deliberately:

* a **synthetic** repository with this repository's directory shape, for the
  mechanism. Fast, and it can be broken on purpose;
* a **real git worktree** of this repository, for the claim that actually
  matters: a representative Python check runs in a fresh checkout and sees that
  checkout's source.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pw_dev.workspace import pyenv
from pw_dev.workspace.sandbox import already_sandboxed

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_VENV = REPO_ROOT / ".venv"

#: The real worktree tests need this repository's own environment to borrow
#: third-party packages from. Without it there is nothing to share.
needs_shared_venv = pytest.mark.skipif(
    not (SHARED_VENV / "bin" / "python").exists(),
    reason="this repository has no .venv to share third-party packages from",
)


# ------------------------------------------------------------------ synthetic
def synthetic_repo(root: Path, *, package: str = "demo_lib",
                   service: str = "demo_service") -> Path:
    """A checkout with this repository's shape and none of its size."""
    (root / "packages" / "demo" / "src" / package).mkdir(parents=True)
    (root / "packages" / "demo" / "src" / package / "__init__.py").write_text(
        "VALUE = 'package'\n", encoding="utf-8")
    (root / "packages" / "demo" / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8")

    (root / "services" / "svc" / "src" / service).mkdir(parents=True)
    (root / "services" / "svc" / "src" / service / "__init__.py").write_text(
        "VALUE = 'service'\n", encoding="utf-8")
    (root / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\ndependencies = ["demo"]\n',
        encoding="utf-8")
    return root


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    return synthetic_repo(tmp_path / "checkout")


@needs_shared_venv
def test_a_prepared_checkout_imports_its_own_source(synthetic: Path):
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.prepared and report.usable, report.problems

    origins = pyenv.module_origins(report.interpreter, ("demo_lib", "demo_service"))
    for module, origin in origins.items():
        assert origin, f"{module} is not importable"
        assert str(synthetic.resolve()) in origin, (module, origin)


@needs_shared_venv
def test_third_party_packages_come_from_the_shared_installation(synthetic: Path):
    """Reuse the dependency cache; do not reuse the source."""
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    origins = pyenv.module_origins(report.interpreter, ("json", "pytest"))
    assert origins["pytest"], "a shared third-party package must still be importable"
    assert str(synthetic.resolve()) not in (origins["pytest"] or "")


@needs_shared_venv
def test_the_original_checkouts_editable_sources_never_enter_sys_path(synthetic: Path):
    """The whole point: a shared site-packages contributes packages, not sources.

    Adding a directory to `sys.path` is not the same as registering it as a site
    directory, so the `__editable__.*.pth` files inside the shared installation
    are never processed and the original checkout's `src` trees never appear.
    """
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    result = subprocess.run(  # noqa: S603 - fixed argv
        [str(report.interpreter), "-c", "import sys, json; print(json.dumps(sys.path))"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    path = json.loads(result.stdout.strip().splitlines()[-1])
    leaked = [entry for entry in path
              if entry.startswith(str(REPO_ROOT)) and entry.endswith("/src")]
    assert not leaked, f"the original checkout's source leaked in: {leaked}"


@needs_shared_venv
def test_a_checkout_that_is_not_this_repository_is_refused(tmp_path: Path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    report = pyenv.prepare(empty, shared_venv=SHARED_VENV)
    assert not report.prepared
    assert not report.usable
    assert any("does not look like this repository" in p for p in report.problems)


def test_a_missing_shared_environment_is_reported_not_raised(synthetic: Path,
                                                             tmp_path: Path):
    report = pyenv.prepare(synthetic, shared_venv=tmp_path / "absent")
    assert not report.prepared
    assert any("has not been created" in p for p in report.problems)


@needs_shared_venv
def test_a_newly_declared_requirement_is_named_rather_than_missed(synthetic: Path):
    """A dependency added in this checkout cannot come from an older installation."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["a-package-nobody-installed"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.prepared, "the virtualenv itself was built"
    assert any("a-package-nobody-installed" in entry
               for entry in report.missing_requirements)
    assert not report.usable, (
        "a declared requirement the shared installation cannot satisfy is a "
        "non-passing condition, not a note: a run whose tests happen not to import "
        "it would otherwise close its gate"
    )
    assert "not installed and cannot be" in report.describe()


@needs_shared_venv
def test_an_optional_extra_is_not_reported_as_missing(synthetic: Path):
    """An extra nobody asked for is not a missing requirement."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\ndependencies = []\n'
        '[project.optional-dependencies]\nextra = ["another-absent-package"]\n',
        encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements == ()


# -------------------------------------------------------------- reuse & staleness
@needs_shared_venv
def test_an_unchanged_checkout_reuses_its_environment(synthetic: Path):
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    second = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert not first.reused and second.reused
    assert first.stamp == second.stamp


@needs_shared_venv
def test_a_new_source_root_invalidates_the_environment(synthetic: Path):
    """Resume must not inherit an environment built for a different tree."""
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    (synthetic / "services" / "added" / "src" / "added_service").mkdir(parents=True)
    (synthetic / "services" / "added" / "src" / "added_service" / "__init__.py").write_text(
        "VALUE = 'added'\n", encoding="utf-8")

    second = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert not second.reused, "a changed source layout must rebuild"
    assert second.stamp != first.stamp
    origins = pyenv.module_origins(second.interpreter, ("added_service",))
    assert origins["added_service"], "the newly added package must be importable"


@needs_shared_venv
def test_a_damaged_stamp_rebuilds_rather_than_reusing(synthetic: Path):
    pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    (synthetic / ".venv" / pyenv.STAMP_NAME).write_text("{}", encoding="utf-8")
    again = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert not again.reused
    assert again.usable


@needs_shared_venv
def test_reuse_can_be_refused_explicitly(synthetic: Path):
    pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    again = pyenv.prepare(synthetic, shared_venv=SHARED_VENV, reuse=False)
    assert not again.reused


# ------------------------------------------------------- wrong-tree detection
@needs_shared_venv
def test_a_wrong_tree_import_is_rejected(synthetic: Path, tmp_path: Path):
    """The construction is designed to prevent this; it is still checked."""
    elsewhere = synthetic_repo(tmp_path / "elsewhere",
                               package="demo_lib", service="demo_service")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    site_dir = next((synthetic / ".venv" / "lib").glob("python*/site-packages"))
    # Point the environment at another tree, exactly as a symlinked `.venv`
    # belonging to the original checkout would have.
    (site_dir / pyenv.PTH_NAME).write_text(
        f"{elsewhere}/packages/demo/src\n{elsewhere}/services/svc/src\n", encoding="utf-8")

    problems = pyenv.assert_module_origins(synthetic, ("demo_lib", "demo_service"))
    assert len(problems) == 2
    assert all("outside" in p for p in problems)
    assert report.interpreter.exists()


@needs_shared_venv
def test_an_unimportable_probe_module_is_a_problem_not_a_pass(synthetic: Path):
    pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    problems = pyenv.assert_module_origins(synthetic, ("module_that_does_not_exist",))
    assert problems and "not importable" in problems[0]


def test_a_checkout_with_no_interpreter_cannot_be_verified(tmp_path: Path):
    problems = pyenv.assert_module_origins(tmp_path, ("anything",))
    assert problems and "no interpreter" in problems[0]


# --------------------------------------------------- the real thing, end to end
@pytest.fixture
def real_worktree(tmp_path: Path):
    """A genuine `git worktree` of this repository, removed afterwards."""
    target = tmp_path / "checkout"
    create = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "worktree", "add", "--detach", str(target), "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    if create.returncode != 0:
        pytest.skip(f"could not create a worktree: {create.stderr.strip()[:200]}")
    try:
        yield target
    finally:
        subprocess.run(  # noqa: S603 - fixed argv
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, check=False,
        )


@needs_shared_venv
def test_a_fresh_checkout_runs_a_representative_python_check(real_worktree: Path):
    """The claim the whole mechanism exists for."""
    report = pyenv.prepare(real_worktree, shared_venv=SHARED_VENV)
    assert report.usable, report.problems
    assert not pyenv.assert_module_origins(
        real_worktree, ("api_gateway", "shared_python", "service_datasets", "pw_dev"))

    result = subprocess.run(  # noqa: S603 - fixed argv
        [str(report.interpreter), "-m", "pytest", "-q", "--import-mode=importlib",
         "-p", "no:cacheprovider", "services/service-access/tests"],
        cwd=real_worktree, capture_output=True, text=True, timeout=900, check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert " passed" in result.stdout


@needs_shared_venv
def test_a_change_made_only_in_the_checkout_is_what_the_checkout_verifies(
        real_worktree: Path):
    """A controlled difference, observed from the checkout and not from the original.

    This is the property a symlinked `.venv` silently destroys.
    """
    report = pyenv.prepare(real_worktree, shared_venv=SHARED_VENV)
    marker = real_worktree / "packages" / "shared-python" / "src" / "shared_python" \
        / "_pw_dev_probe.py"
    marker.write_text("ORIGIN = 'the checkout'\n", encoding="utf-8")

    seen = subprocess.run(  # noqa: S603 - fixed argv
        [str(report.interpreter), "-c",
         "from shared_python import _pw_dev_probe as p; print(p.ORIGIN, p.__file__)"],
        cwd=real_worktree, capture_output=True, text=True, timeout=120, check=False,
    )
    assert seen.returncode == 0, seen.stderr
    assert "the checkout" in seen.stdout
    assert str(real_worktree.resolve()) in seen.stdout

    # The original installation is untouched and does not see it.
    original = subprocess.run(  # noqa: S603 - fixed argv
        [str(SHARED_VENV / "bin" / "python"), "-c",
         "import importlib.util as u;"
         "print('FOUND' if u.find_spec('shared_python._pw_dev_probe') else 'ABSENT')"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert "ABSENT" in original.stdout, (
        "the original checkout must not see a file that exists only in the worktree"
    )


@needs_shared_venv
def test_console_launchers_are_reproduced_for_the_new_environment(real_worktree: Path):
    """`scripts/test.sh` activates the environment and calls `pytest` by name."""
    pyenv.prepare(real_worktree, shared_venv=SHARED_VENV)
    bin_dir = real_worktree / ".venv" / "bin"
    assert (bin_dir / "pytest").exists(), "verify-release.sh calls pytest by name"

    launched = subprocess.run(  # noqa: S603 - fixed argv
        [str(bin_dir / "pytest"), "--version"],
        cwd=real_worktree, capture_output=True, text=True, timeout=120, check=False,
    )
    assert launched.returncode == 0, launched.stderr

    text = (bin_dir / "pytest").read_text(encoding="utf-8")
    assert str(SHARED_VENV) not in text, (
        "a launcher still pointing at the original environment would run the "
        "original interpreter, and with it the original source"
    )


@needs_shared_venv
def test_preparing_an_environment_does_not_change_the_tree_fingerprint(
        real_worktree: Path):
    """Evidence is bound to a fingerprint; giving a checkout an interpreter is
    not a change to the code being verified."""
    from pw_dev.util.hashing import tree_fingerprint

    before = tree_fingerprint(real_worktree)
    pyenv.prepare(real_worktree, shared_venv=SHARED_VENV)
    assert tree_fingerprint(real_worktree) == before


def test_the_environment_directory_is_ignored_by_git():
    ignored = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "check-ignore", "-q", ".venv"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False,
    )
    assert ignored.returncode == 0, "a prepared environment must stay untracked"


def test_no_secret_is_copied_into_a_prepared_environment():
    """Only launchers are reproduced, and only from `bin/`."""
    source = Path(pyenv.__file__).read_text(encoding="utf-8")
    for forbidden in (".env", "auth.json", "credentials", "state.sqlite3"):
        assert f'"{forbidden}"' not in source, (
            f"the preparer must not name {forbidden}"
        )
    assert "shared_venv / \"bin\"" in source or 'shared_venv / "bin"' in source


def test_python_is_not_borrowed_from_the_original_bin(synthetic: Path, tmp_path: Path):
    """The new environment's own interpreter, not the old one's."""
    assert "python" in pyenv._SKIP_SCRIPTS
    assert "pip" in pyenv._SKIP_SCRIPTS
    assert sys.executable  # the test process itself is unaffected


# ============ the environment is not a surface a worker can hand the controller
def test_the_profile_a_claude_worker_runs_under_carries_both_carve_outs(tmp_path: Path):
    """Asserted from the rendered profile, not from the source that builds it.

    The first attempt initialised the denials with the checkout's `.venv` and
    the Claude branch then *assigned* over them, dropping the carve-out for the
    one adapter that actually writes. A test that searched the source for the
    initialising line passed anyway. This renders the profile the worker really
    gets and looks in it.
    """
    from pw_dev.workspace.sandbox import build_profile, claude_config_denials

    checkout = tmp_path / "checkout"
    (checkout / ".venv").mkdir(parents=True)
    claude_config = tmp_path / ".claude"
    (claude_config / "plugins").mkdir(parents=True)

    # Exactly what `_call_provider` composes for a Claude worker.
    denials = [checkout / ".venv"]
    denials.extend(claude_config_denials(claude_config))
    profile = build_profile([checkout, claude_config], denials)

    assert f'(subpath "{checkout}")' in profile, "the worker still owns its checkout"
    assert f'(subpath "{checkout / ".venv"}")' in profile, (
        "the interpreter the controller runs must be denied to the worker"
    )
    assert f'(subpath "{claude_config / "plugins"}")' in profile, (
        "the Claude configuration carve-outs must survive alongside it"
    )
    denied = profile[profile.index("Carved back out"):]
    assert str(checkout / ".venv") in denied and str(claude_config / "plugins") in denied


def test_the_controller_extends_the_denials_rather_than_replacing_them():
    source = Path(__import__("pw_dev.controller.run", fromlist=["run"]).__file__)
    text = source.read_text(encoding="utf-8")
    assert 'denials: list[Path] = [Path(root) / ".venv" for root in (sandbox_roots or [])]' \
        in text
    assert "denials.extend(claude_config_denials(claude_config))" in text
    assert "denials = claude_config_denials(claude_config)" not in text, (
        "assigning here dropped the environment carve-out"
    )


@needs_shared_venv
@pytest.mark.skipif(
    already_sandboxed(),
    reason="Seatbelt profiles do not nest; this proof needs an unsandboxed host",
)
def test_seatbelt_denies_writes_to_a_carved_out_environment(tmp_path: Path):
    """Not asserted from the profile text: exercised, like `doctor` does."""
    import subprocess as sp

    from pw_dev.workspace.sandbox import build_profile, detect_sandbox_support

    support = detect_sandbox_support(probe=False)
    if not support.available:
        pytest.skip(f"this host cannot enforce a write boundary ({support.mechanism})")

    checkout = synthetic_repo(tmp_path / "checkout")
    report = pyenv.prepare(checkout, shared_venv=SHARED_VENV)
    assert report.usable

    profile = tmp_path / "profile.sb"
    profile.write_text(build_profile([checkout], [checkout / ".venv"]), encoding="utf-8")

    def run(script: str) -> int:
        return sp.run(  # noqa: S603 - fixed argv
            ["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/sh", "-c", script],
            capture_output=True, text=True, timeout=120, check=False,
        ).returncode

    assert run(f"echo ok > {checkout}/allowed.txt") == 0, (
        "the worker must still be able to write its own checkout"
    )
    assert run(f"echo evil > {checkout}/.venv/bin/python") != 0, (
        "rewriting the interpreter the controller runs must be denied"
    )
    site = next((checkout / ".venv" / "lib").glob("python*/site-packages"))
    assert run(f"echo /tmp > {site}/{pyenv.PTH_NAME}") != 0, (
        "rewriting the path composition must be denied too"
    )


@needs_shared_venv
def test_a_tampered_environment_is_rebuilt_before_anything_runs_in_it(tmp_path: Path):
    """Where the host cannot enforce the carve-out, the rebuild is what remains."""
    checkout = synthetic_repo(tmp_path / "checkout")
    pyenv.prepare(checkout, shared_venv=SHARED_VENV)

    site = next((checkout / ".venv" / "lib").glob("python*/site-packages"))
    elsewhere = synthetic_repo(tmp_path / "elsewhere")
    (site / pyenv.PTH_NAME).write_text(
        f"{elsewhere}/packages/demo/src\n", encoding="utf-8")
    assert pyenv.assert_module_origins(checkout, ("demo_lib",)), (
        "the tampered environment resolves outside the checkout"
    )

    pyenv.prepare(checkout, shared_venv=SHARED_VENV, reuse=False)
    assert not pyenv.assert_module_origins(checkout, ("demo_lib", "demo_service")), (
        "a rebuild restores the composition the controller relies on"
    )


def test_the_controller_rebuilds_before_running_worker_requested_checks():
    source = Path(__import__("pw_dev.controller.run", fromlist=["run"]).__file__)
    text = source.read_text(encoding="utf-8")
    assert "after the worker ran" in text
    assert "after a repair round" in text


# ================== requirements are checked against what is really installed
@needs_shared_venv
def test_a_version_that_does_not_match_is_not_satisfied_by_the_name(synthetic: Path):
    """`pydantic>=999` is not satisfied by the pydantic that happens to be there.

    Matching on the normalized name alone reported any installed version as
    satisfying any specifier.
    """
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["pydantic>=999"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements, "an impossible specifier is unsatisfied"
    assert "pydantic" in report.missing_requirements[0]
    assert "installed" in report.missing_requirements[0]
    assert not report.usable


@needs_shared_venv
def test_a_version_that_does_match_is_satisfied(synthetic: Path):
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["pydantic>=1"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements == ()
    assert report.usable


@needs_shared_venv
def test_a_requirement_that_does_not_apply_here_is_not_reported(synthetic: Path):
    """An environment marker that evaluates false is not a missing dependency."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["a-windows-only-package; sys_platform == \'win32\'"]\n',
        encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements == ()


@needs_shared_venv
def test_a_bare_directory_is_not_mistaken_for_an_installed_distribution(
        synthetic: Path, tmp_path: Path):
    """Satisfaction is asked of `importlib.metadata`, not of `ls site-packages`."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["demo-lib"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    # `demo_lib` is importable from the checkout and has no distribution
    # metadata anywhere, so it is correctly reported as unsatisfied.
    assert any("demo-lib" in entry for entry in report.missing_requirements)


# =================================== startup hooks are not a checkout's to add
@pytest.mark.parametrize("hook", [
    "sitecustomize.py", "usercustomize.py",
    # A package directory satisfies `import sitecustomize` exactly as the module
    # file does, so both shapes have to be refused.
    "sitecustomize/__init__.py", "usercustomize/__init__.py",
])
def test_a_startup_hook_is_never_writable_by_a_task(hook: str):
    """Python imports these by itself, from anywhere on `sys.path`.

    A first-party source root is on the `sys.path` of the interpreter the
    controller runs verification with, unsandboxed — so a task able to add one
    would choose what runs during every check, and could exit zero in silence.
    CPython ships neither; the one on this machine belongs to Homebrew, which is
    luck rather than a boundary.
    """
    from pw_dev.workspace.guard import PathGuard, PathViolation

    with pytest.raises(PathViolation, match="forbidden"):
        PathGuard(["**"]).check(f"services/service-datasets/src/{hook}")
    with pytest.raises(PathViolation, match="forbidden"):
        PathGuard(["**"]).check(hook)


@needs_shared_venv
@pytest.mark.parametrize("hook", [
    "sitecustomize.py", "usercustomize.py",
    "sitecustomize/__init__.py", "usercustomize/__init__.py",
])
def test_a_checkout_carrying_a_startup_hook_cannot_be_prepared(synthetic: Path,
                                                               hook: str):
    """Belt and braces: the guard stops a task writing one; this stops one that
    arrived any other way from ever reaching an interpreter."""
    target = synthetic / "services" / "svc" / "src" / hook
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import os; os._exit(0)\n", encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert not report.prepared
    assert not report.usable
    assert any("imported automatically" in p for p in report.problems)
    assert any(hook.split("/")[0] in p for p in report.problems)


# ============================= the stamp covers everything reuse depends on
@needs_shared_venv
def test_a_changed_launcher_inventory_invalidates_the_environment(synthetic: Path,
                                                                  tmp_path: Path):
    """Launchers are copied, so a change to the shared ones must rebuild."""
    shared = tmp_path / "shared"
    (shared / "bin").mkdir(parents=True)
    for name in ("python", "python3"):
        (shared / "bin" / name).symlink_to(SHARED_VENV / "bin" / "python")
    (shared / "bin" / "atool").write_text(
        f"#!{shared}/bin/python\nprint('v1')\n", encoding="utf-8")

    first = pyenv.prepare(synthetic, shared_venv=shared)
    if not first.prepared:
        pytest.skip(f"the minimal shared venv is not usable here: {first.problems}")
    assert pyenv.prepare(synthetic, shared_venv=shared).reused

    (shared / "bin" / "another-tool").write_text(
        f"#!{shared}/bin/python\nprint('v1')\n", encoding="utf-8")
    assert not pyenv.prepare(synthetic, shared_venv=shared).reused, (
        "a new launcher in the shared environment must reach the checkout"
    )


@needs_shared_venv
def test_unreadable_dependency_metadata_is_reported_not_treated_as_none(
        synthetic: Path):
    """Not knowing what a checkout requires is not the same as it requiring nothing.

    Skipping a malformed `pyproject.toml` silently made a broken checkout look
    like one with no dependencies, which is the one answer ignorance must never
    produce.
    """
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        "[project\nthis is not toml", encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements, "the parse failure has to surface"
    assert "could not read dependency declarations" in report.missing_requirements[0]
    assert not report.usable


@needs_shared_venv
def test_an_importable_hook_package_would_have_run(synthetic: Path):
    """Establishes the thing the refusal prevents, rather than asserting a rule."""
    import subprocess as sp

    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    root = synthetic / "services" / "svc" / "src"
    package = root / "sitecustomize"
    package.mkdir()
    (package / "__init__.py").write_text("MARKER = 'would have run'\n", encoding="utf-8")

    resolved = sp.run(  # noqa: S603 - fixed argv
        [str(report.interpreter), "-c",
         "import importlib.util as u; s = u.find_spec('sitecustomize');"
         " print(s.origin if s else 'none')"],
        cwd=synthetic, capture_output=True, text=True, timeout=120, check=False,
    ).stdout.strip()
    # On a host whose Python ships its own stdlib `sitecustomize` (Homebrew does)
    # the checkout's is shadowed. That is luck, not a boundary, which is why the
    # refusal below does not depend on it.
    assert resolved

    assert pyenv.startup_hooks_in([root]), "a hook package must be detected"
    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV, reuse=False).prepared


# ============= every importable form of a startup hook, not two filenames
def test_every_importable_hook_suffix_this_interpreter_supports_is_reserved():
    """Built from `importlib.machinery`, so a supported suffix cannot be forgotten."""
    import importlib.machinery as machinery

    from pw_dev.workspace.guard import PathGuard, PathViolation

    suffixes = set(machinery.SOURCE_SUFFIXES + machinery.BYTECODE_SUFFIXES
                   + machinery.EXTENSION_SUFFIXES)
    assert ".pyc" in suffixes and ".so" in suffixes
    for name in ("sitecustomize", "usercustomize"):
        for suffix in suffixes:
            target = f"services/service-datasets/src/{name}{suffix}"
            with pytest.raises(PathViolation, match="forbidden"):
                PathGuard(["**"]).check(target)


@needs_shared_venv
@pytest.mark.parametrize("suffix", [".py", ".pyc", ".so"])
def test_a_hook_in_any_importable_form_stops_preparation(synthetic: Path, suffix: str):
    root = synthetic / "services" / "svc" / "src"
    (root / f"sitecustomize{suffix}").write_bytes(b"\x00")
    assert pyenv.startup_hooks_in([root])
    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV).prepared


# ================================ requirements: the remaining fail-open cases
@needs_shared_venv
def test_a_missing_extra_is_not_satisfied_by_the_base_package(synthetic: Path):
    """`httpx[socks]` needs socksio; httpx alone does not supply it."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["httpx[socks]>=0"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not report.missing_requirements:
        pytest.skip("this environment happens to have every httpx extra installed")
    assert "socks" in report.missing_requirements[0]
    assert not report.usable


@needs_shared_venv
def test_an_extra_that_does_not_exist_is_reported(synthetic: Path):
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["httpx[no-such-extra]>=0"]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert any("no such extra" in entry for entry in report.missing_requirements)


@needs_shared_venv
def test_a_malformed_dependency_entry_is_reported_not_discarded(synthetic: Path):
    """Dropping it before the parser saw it made it silently not a dependency."""
    (synthetic / "services" / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0.1.0"\n'
        'dependencies = ["=== not a requirement ==="]\n', encoding="utf-8")
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert report.missing_requirements
    assert "not a usable requirement" in report.missing_requirements[0]
    assert not report.usable


@needs_shared_venv
def test_a_same_size_launcher_rewrite_within_one_second_still_rebuilds(
        synthetic: Path, tmp_path: Path):
    """Second-resolution mtimes let a same-sized rewrite reuse a stale copy."""
    shared = tmp_path / "shared"
    (shared / "bin").mkdir(parents=True)
    for name in ("python", "python3"):
        (shared / "bin" / name).symlink_to(SHARED_VENV / "bin" / "python")
    launcher = shared / "bin" / "atool"
    launcher.write_text(f"#!{shared}/bin/python\nprint('v1')\n", encoding="utf-8")

    first = pyenv.prepare(synthetic, shared_venv=shared)
    if not first.prepared:
        pytest.skip(f"the minimal shared venv is not usable here: {first.problems}")

    launcher.write_text(f"#!{shared}/bin/python\nprint('v2')\n", encoding="utf-8")
    assert len("v1") == len("v2"), "the rewrite is the same size, on purpose"
    assert not pyenv.prepare(synthetic, shared_venv=shared).reused


def test_a_launcher_rewrite_that_restores_its_timestamp_still_rebuilds(
        synthetic: Path, tmp_path: Path):
    """Metadata is chosen by whoever writes the file; content is not.

    Size, mode and modification time can all be put back exactly, so an
    environment that trusted them would keep running a launcher that is no
    longer the one it was stamped against. The manifest carries a digest of
    the bytes for this case.
    """
    shared = tmp_path / "shared"
    (shared / "bin").mkdir(parents=True)
    for name in ("python", "python3"):
        (shared / "bin" / name).symlink_to(SHARED_VENV / "bin" / "python")
    launcher = shared / "bin" / "atool"
    launcher.write_text(f"#!{shared}/bin/python\nprint('v1')\n", encoding="utf-8")
    before = launcher.stat()

    first = pyenv.prepare(synthetic, shared_venv=shared)
    if not first.prepared:
        pytest.skip(f"the minimal shared venv is not usable here: {first.problems}")

    launcher.write_text(f"#!{shared}/bin/python\nprint('v2')\n", encoding="utf-8")
    os.utime(launcher, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.chmod(launcher, before.st_mode)
    after = launcher.stat()
    assert (after.st_size, after.st_mtime_ns, after.st_mode) == (
        before.st_size, before.st_mtime_ns, before.st_mode), (
        "the point of the test is that every metadata field is identical")

    assert not pyenv.prepare(synthetic, shared_venv=shared).reused


@needs_shared_venv
def test_an_environment_built_on_a_prepared_one_still_finds_its_packages(
        synthetic: Path, tmp_path: Path):
    """Layering. The candidate's own suite runs inside a prepared environment.

    A prepared environment keeps no packages of its own: it names the
    directories to import from in a `.pth`. A directory on `sys.path` is not a
    site directory, so that `.pth` is not processed again for the next layer —
    and every third-party package vanished one level down. `packaging` missing
    is what it looked like from the outside.
    """
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    assert first.prepared, first.problems

    second_checkout = tmp_path / "layered"
    (second_checkout / "services" / "svc" / "src").mkdir(parents=True)
    (second_checkout / "pyproject.toml").write_text(
        "[project]\nname = 'layered'\nversion = '0'\n", encoding="utf-8")

    # The prepared environment is now the *base* for the next one.
    second = pyenv.prepare(second_checkout, shared_venv=synthetic / ".venv")
    assert second.prepared, second.problems

    origins = pyenv.module_origins(second.interpreter, ("pytest",))
    assert origins["pytest"], (
        "a package reachable from the base environment must stay reachable one "
        "layer up; losing it is what made the orchestrator's own suite fail "
        "inside a candidate"
    )


def test_layering_carries_packages_but_never_source_roots(
        synthetic: Path, tmp_path: Path):
    """The inheritance must not undo the isolation it is layered on top of."""
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")

    inherited = pyenv.third_party_sites(first.interpreter)
    assert inherited, "the chain must be recorded"
    for entry in inherited:
        assert str(synthetic.resolve()) not in str(entry), (
            f"{entry} is inside the checkout; only site directories propagate"
        )
        assert entry.name == "site-packages" or "site-packages" in str(entry), entry


def test_an_unexpected_pth_stops_the_environment_being_reused(synthetic: Path):
    """Python executes a `.pth` at interpreter start, before any check runs.

    An inventory of expected *names* did not notice a file nobody looked for,
    so a planted one left every recorded digest unchanged.
    """
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")
    assert pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused

    site_dir = pyenv.site_packages_of(first.interpreter)
    (site_dir / "zz-extra.pth").write_text("import os\n", encoding="utf-8")

    assert pyenv.unexpected_startup_files(synthetic / ".venv") == ["zz-extra.pth"]
    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused


def test_a_startup_hook_planted_in_the_environment_stops_reuse(synthetic: Path):
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")
    site_dir = pyenv.site_packages_of(first.interpreter)
    (site_dir / "sitecustomize.py").write_text("x = 1\n", encoding="utf-8")

    assert "sitecustomize.py" in pyenv.unexpected_startup_files(synthetic / ".venv")
    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused


def test_an_unreadable_environment_is_rebuilt_rather_than_matched(synthetic: Path):
    """`None == None` compared equal, so unreadable counted as unchanged."""
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")
    stamp_path = synthetic / ".venv" / pyenv.STAMP_NAME
    recorded = json.loads(stamp_path.read_text(encoding="utf-8"))
    recorded["contents"] = None
    stamp_path.write_text(json.dumps(recorded), encoding="utf-8")

    assert not pyenv._stamp_matches(synthetic / ".venv", recorded["stamp"])


def test_a_rewritten_pth_is_not_reused_however_the_stamp_reads(synthetic: Path):
    """The stamp described what the environment was built from, not what it is.

    `.pth` decides where imports resolve. A matching stamp beside a rewritten
    one still counted as reusable, which made the "the base imports from it"
    provenance test circular.
    """
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")
    assert pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused

    site_dir = pyenv.site_packages_of(first.interpreter)
    pth = site_dir / pyenv.PTH_NAME
    pth.write_text(pth.read_text(encoding="utf-8") + "/tmp\n", encoding="utf-8")

    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused, (
        "an environment whose own configuration changed is rebuilt, not reused"
    )


def test_a_replaced_launcher_in_the_prepared_environment_forces_a_rebuild(
        synthetic: Path):
    first = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not first.prepared:
        pytest.skip(f"the shared venv is not usable here: {first.problems}")
    assert pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused

    bin_dir = synthetic / ".venv" / "bin"
    planted = bin_dir / "pytest"
    planted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    assert not pyenv.prepare(synthetic, shared_venv=SHARED_VENV).reused


def test_a_poisoned_inheritance_manifest_cannot_add_a_source_tree(
        synthetic: Path, tmp_path: Path):
    """The manifest lives in a checkout, so it is evidence, not authority.

    Verification grants the checkout write access. If the recorded chain were
    taken at face value, a checkout could name another checkout's `src` and put
    it on the next layer's `sys.path` -- undoing the isolation the whole module
    exists to provide.
    """
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not report.prepared:
        pytest.skip(f"the shared venv is not usable here: {report.problems}")

    site_dir = pyenv.site_packages_of(report.interpreter)
    manifest = site_dir / pyenv.THIRD_PARTY_NAME
    assert manifest.exists(), "the honest chain is recorded"

    intruder = tmp_path / "somebody-else" / "src"
    intruder.mkdir(parents=True)
    manifest.write_text(json.dumps([str(intruder)]), encoding="utf-8")

    with pytest.raises(pyenv.IdentityUnavailable) as refused:
        pyenv.third_party_sites(report.interpreter)
    assert "source tree" in str(refused.value)


def test_a_directory_merely_named_site_packages_is_not_inherited(
        synthetic: Path, tmp_path: Path):
    """The basename check alone was not provenance, and a name is cheap.

    A checkout can create `fake/site-packages` holding a link to another
    checkout's source. What makes a directory inheritable is that the base
    interpreter actually imports from it.
    """
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not report.prepared:
        pytest.skip(f"the shared venv is not usable here: {report.problems}")

    counterfeit = tmp_path / "fake" / "site-packages"
    counterfeit.mkdir(parents=True)
    (counterfeit / "shared_python").symlink_to(tmp_path)

    site_dir = pyenv.site_packages_of(report.interpreter)
    (site_dir / pyenv.THIRD_PARTY_NAME).write_text(
        json.dumps([str(counterfeit)]), encoding="utf-8")

    with pytest.raises(pyenv.IdentityUnavailable) as refused:
        pyenv.third_party_sites(report.interpreter)
    assert "does not import from" in str(refused.value)


def test_an_inheritance_manifest_that_is_not_a_list_is_refused(
        synthetic: Path):
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not report.prepared:
        pytest.skip(f"the shared venv is not usable here: {report.problems}")
    site_dir = pyenv.site_packages_of(report.interpreter)
    (site_dir / pyenv.THIRD_PARTY_NAME).write_text('"just a string"', encoding="utf-8")

    with pytest.raises(pyenv.IdentityUnavailable):
        pyenv.third_party_sites(report.interpreter)


def test_a_relative_entry_in_the_manifest_is_refused(synthetic: Path):
    report = pyenv.prepare(synthetic, shared_venv=SHARED_VENV)
    if not report.prepared:
        pytest.skip(f"the shared venv is not usable here: {report.problems}")
    site_dir = pyenv.site_packages_of(report.interpreter)
    (site_dir / pyenv.THIRD_PARTY_NAME).write_text('["../elsewhere"]', encoding="utf-8")

    with pytest.raises(pyenv.IdentityUnavailable):
        pyenv.third_party_sites(report.interpreter)


def test_hashing_a_launcher_refuses_to_follow_a_symlink(tmp_path: Path):
    """The branch is chosen by lstat; the read must not go somewhere else.

    `Path.open` follows a final symlink, so selecting the regular-file branch
    and then reading by name left a window: swap the entry for a symlink in
    between and the caller hashes whatever it points at, outside the directory
    entirely. Opening with O_NOFOLLOW closes the window by refusing.
    """
    (tmp_path / "outside.txt").write_text("not mine to read\n", encoding="utf-8")
    link = tmp_path / "atool"
    link.symlink_to(tmp_path / "outside.txt")

    with pytest.raises(OSError) as refused:
        pyenv._digest_descriptor(link)
    assert refused.value.errno == errno.ELOOP

    plain = tmp_path / "plain"
    plain.write_text("mine\n", encoding="utf-8")
    digest, stat_result = pyenv._digest_descriptor(plain)
    assert digest and stat_result.st_size == len("mine\n"), (
        "a regular file is still hashed, and its metadata comes from the "
        "descriptor that was hashed"
    )


def test_a_launcher_that_cannot_be_read_refuses_the_environment(
        synthetic: Path, tmp_path: Path):
    """An unreadable launcher is not an absent one, and must not be skipped.

    Omitting it left the stamp describing only the launchers that happened to
    be readable, so an environment whose identity was partly unknown could be
    reused on the strength of the part that was known.
    """
    shared = tmp_path / "shared"
    (shared / "bin").mkdir(parents=True)
    for name in ("python", "python3"):
        (shared / "bin" / name).symlink_to(SHARED_VENV / "bin" / "python")
    launcher = shared / "bin" / "atool"
    launcher.write_text(f"#!{shared}/bin/python\nprint('v1')\n", encoding="utf-8")

    first = pyenv.prepare(synthetic, shared_venv=shared)
    if not first.prepared:
        pytest.skip(f"the minimal shared venv is not usable here: {first.problems}")

    launcher.chmod(0o000)
    try:
        report = pyenv.prepare(synthetic, shared_venv=shared)
    finally:
        launcher.chmod(0o644)

    assert not report.prepared
    assert not report.usable
    assert any("atool" in problem for problem in report.problems), report.problems
    assert any("could not be identified" in problem for problem in report.problems)


def test_an_interpreter_rewritten_in_place_changes_its_identity(tmp_path: Path):
    """Path, size and timestamp are all chosen by whoever writes the file.

    Replacing the interpreter's bytes at the same size and putting the
    timestamp back left every recorded field identical, so an environment built
    on one interpreter was reused against another.
    """
    interpreter = tmp_path / "python"
    interpreter.write_bytes(b"#!/bin/sh\necho one\n")
    interpreter.chmod(0o755)
    before_stat = interpreter.stat()
    before = pyenv._interpreter_identity(interpreter)

    interpreter.write_bytes(b"#!/bin/sh\necho two\n")
    os.utime(interpreter, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    os.chmod(interpreter, before_stat.st_mode)
    after = pyenv._interpreter_identity(interpreter)

    assert (after["size"], after["mtime_ns"], after["mode"], after["path"]) == (
        before["size"], before["mtime_ns"], before["mode"], before["path"]), (
        "the point of the test is that every metadata field is identical")
    assert after["content"] != before["content"]


def test_an_unidentifiable_interpreter_refuses_rather_than_guessing(tmp_path: Path):
    """No identity means no reuse decision, so it is an error, not a blank."""
    missing = tmp_path / "gone"
    with pytest.raises(pyenv.IdentityUnavailable):
        pyenv._interpreter_identity(missing)


def test_a_launcher_symlink_is_stamped_by_its_target_not_its_contents(
        tmp_path: Path):
    """Repointing a launcher symlink changes what runs, so it changes the stamp."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "one").write_text("#!/bin/sh\necho one\n", encoding="utf-8")
    (tmp_path / "two").write_text("#!/bin/sh\necho one\n", encoding="utf-8")
    link = bin_dir / "atool"
    link.symlink_to(tmp_path / "one")

    before = pyenv._launcher_manifest(bin_dir)
    link.unlink()
    link.symlink_to(tmp_path / "two")
    after = pyenv._launcher_manifest(bin_dir)

    assert before != after, "the two targets have identical contents, on purpose"
    assert before[0][-1] == f"link:{tmp_path / 'one'}"
    assert after[0][-1] == f"link:{tmp_path / 'two'}"
