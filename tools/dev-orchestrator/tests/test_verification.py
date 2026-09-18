"""The verification runner: what counts as evidence, and what does not."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pw_dev.errors import PolicyViolation
from pw_dev.state.db import RunStore
from pw_dev.util.hashing import tree_fingerprint
from pw_dev.verify.registry import Check, Registry
from pw_dev.verify.runner import SUCCESS_OUTCOMES, Outcome, VerificationRunner
from pw_dev.workspace.guard import PathViolation


def _runner(store: RunStore, tmp_path: Path, checks=None, *, spec_digest="spec-1") -> VerificationRunner:
    registry = Registry(checks) if checks else Registry()
    run_id = store.create_run(brain="automatic", config_snapshot={}, publication_mode="none",
                              deadline_epoch=None)
    return VerificationRunner(
        registry, store=store, run_id=run_id, base_commit="b" * 40,
        spec_digest=spec_digest, artifacts_dir=tmp_path / "evidence",
    )


def _check(check_id: str, argv: tuple[str, ...], **kwargs) -> Check:
    return Check(id=check_id, description=check_id, argv=argv, timeout_seconds=30, **kwargs)


# ------------------------------------------------------------------ registry
def test_an_agent_cannot_invent_a_check():
    """Agents request ids. An agent that can supply a command owns the gate."""
    registry = Registry()
    with pytest.raises(PolicyViolation, match="not a registered verification"):
        registry.get("rm -rf /")
    with pytest.raises(PolicyViolation, match="Registered ids"):
        registry.get("python:tests; curl evil.example")


def test_unknown_ids_are_listed_without_raising_during_plan_validation():
    registry = Registry()
    assert registry.validate_ids(["python:tests", "made:up"]) == ["made:up"]


def test_a_parameterised_check_still_validates_its_parameter():
    registry = Registry()
    bound = registry.with_parameter("python:service", "{service_path}", "services/service-datasets")
    assert "services/service-datasets" in bound.argv
    with pytest.raises(PathViolation):
        registry.with_parameter("python:service", "{service_path}", "../../etc")


def test_the_registry_ids_match_the_repository_scripts():
    """Drift here means the controller is running something other than the gate."""
    registry = Registry()
    for expected in ("repo:verify", "python:ruff", "python:tests", "web:lint",
                     "web:typecheck", "web:tests", "web:build", "connectors:servers",
                     "orchestrator:ruff", "orchestrator:tests"):
        assert expected in registry, f"{expected} is missing from the registry"
    assert {c.id for c in registry.gates()} >= {"repo:verify", "orchestrator:tests"}


# ------------------------------------------------------------------ outcomes
def test_a_passing_command_is_pass(store, tmp_path):
    runner = _runner(store, tmp_path, (_check("ok", (sys.executable, "-c", "print('fine')")),))
    record = runner.run_check("ok", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.PASS
    assert record["exit_status"] == 0
    assert record["output_digest"]


def test_a_failing_command_is_fail(store, tmp_path):
    runner = _runner(store, tmp_path, (_check("bad", (sys.executable, "-c", "import sys; sys.exit(3)")),))
    record = runner.run_check("bad", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.FAIL
    assert record["exit_status"] == 3


def test_a_run_that_exercised_nothing_is_a_skip(store, tmp_path):
    """Everything skipped and nothing ran. Exit zero does not make that a result."""
    output = "===== 12 skipped in 1.20s ====="
    runner = _runner(store, tmp_path, (_check("skips", (sys.executable, "-c", f"print({output!r})")),))
    record = runner.run_check("skips", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.SKIP
    assert record["outcome"] not in SUCCESS_OUTCOMES
    assert "12" in record["detail"]


def test_a_run_with_passes_and_skips_passes_and_records_the_gap(store, tmp_path):
    """The correction. Three cases ran and passed; twelve did not run.

    Reading that as "no result" was too strong, and not in a way that made the
    tool stricter: this repository's own suite skips 578 cases whenever the
    optional MySQL and MariaDB servers are absent, so every gate was
    permanently unclosable on an ordinary machine and no run could ever reach
    COMMIT. The gap is real and stays in the evidence; it is not a reason to
    discard the 3 results that exist.
    """
    output = "===== 3 passed, 12 skipped in 1.20s ====="
    runner = _runner(store, tmp_path, (_check("mixed", (sys.executable, "-c", f"print({output!r})")),))
    record = runner.run_check("mixed", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.PASS
    assert record["skipped"] == 12
    assert "12 were skipped" in record["detail"]
    assert "not covered by this evidence" in record["detail"]


def test_a_failure_summary_is_not_mistaken_for_a_skip(store, tmp_path):
    output = "===== 1 failed, 2 skipped in 0.3s ====="
    runner = _runner(store, tmp_path, (
        _check("mixed", (sys.executable, "-c", f"import sys; print({output!r}); sys.exit(1)")),
    ))
    record = runner.run_check("mixed", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.FAIL


def test_a_missing_prerequisite_is_not_run_not_pass(store, tmp_path):
    runner = _runner(store, tmp_path, (
        _check("needs-venv", (sys.executable, "-c", "print('x')"), requires=("venv",)),
    ))
    record = runner.run_check("needs-venv", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.NOT_RUN
    assert "did not execute" in record["detail"]
    assert "not the same as passing" in record["detail"]


def test_unreachable_infrastructure_is_its_own_outcome(store, tmp_path):
    """A local run with no database is not CI coverage, and says so."""
    runner = _runner(store, tmp_path, (
        _check("connectors", (sys.executable, "-c", "print('x')"),
               infra=("postgres", "mysql", "mariadb"),
               infra_note="CI starts these three servers and fails if they are unreachable."),
    ))
    record = runner.run_check("connectors", checkout=tmp_path, candidate_fingerprint="tree:x")
    if record["outcome"] == Outcome.PASS:
        pytest.skip("a database is listening on this host, so the check really did run")
    assert record["outcome"] == Outcome.INFRA_UNAVAILABLE
    assert "CI starts these three servers" in record["detail"]


def test_a_timeout_is_a_timeout_not_a_failure(store, tmp_path):
    runner = _runner(store, tmp_path, (
        Check(id="slow", description="slow", argv=(sys.executable, "-c", "import time; time.sleep(30)"),
              timeout_seconds=1),
    ))
    record = runner.run_check("slow", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.TIMEOUT
    assert "unknown" in record["detail"]


def test_an_unrunnable_command_is_error_not_pass(store, tmp_path):
    runner = _runner(store, tmp_path, (_check("nope", ("definitely-not-a-binary-xyz",)),))
    record = runner.run_check("nope", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.ERROR


def test_only_pass_lets_a_gate_close():
    assert SUCCESS_OUTCOMES == {Outcome.PASS}
    for outcome in (Outcome.SKIP, Outcome.NOT_RUN, Outcome.INFRA_UNAVAILABLE,
                    Outcome.TIMEOUT, Outcome.FAIL, Outcome.ERROR):
        assert outcome not in SUCCESS_OUTCOMES


# ------------------------------------------------------------------ binding
def test_evidence_is_bound_to_the_tree_it_was_produced_against(store, tmp_path):
    runner = _runner(store, tmp_path, (_check("ok", (sys.executable, "-c", "print('x')")),),
                     spec_digest="spec-abc")
    record = runner.run_check("ok", checkout=tmp_path, candidate_fingerprint="tree:aaa")
    assert record["candidate_fingerprint"] == "tree:aaa"
    assert record["base_commit"] == "b" * 40
    assert record["spec_digest"] == "spec-abc"
    assert record["environment_digest"]


def test_evidence_for_one_candidate_does_not_return_another_s(store, tmp_path):
    runner = _runner(store, tmp_path, (_check("ok", (sys.executable, "-c", "print('x')")),))
    runner.run_check("ok", checkout=tmp_path, candidate_fingerprint="tree:old")
    runner.run_check("ok", checkout=tmp_path, candidate_fingerprint="tree:new")
    assert len(store.evidence_for(runner.run_id, candidate_fingerprint="tree:new")) == 1
    assert len(store.evidence_for(runner.run_id)) == 2


def test_a_new_untracked_file_changes_the_fingerprint(tmp_path: Path):
    """Evidence must not survive a change a `git diff` would not show."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = tree_fingerprint(tmp_path)
    (tmp_path / "new_file.py").write_text("y = 2\n", encoding="utf-8")
    assert tree_fingerprint(tmp_path) != before


def test_making_a_file_executable_changes_the_fingerprint(tmp_path: Path):
    script = tmp_path / "run.sh"
    script.write_text("echo hi\n", encoding="utf-8")
    before = tree_fingerprint(tmp_path)
    script.chmod(0o755)
    assert tree_fingerprint(tmp_path) != before


def test_build_output_does_not_invalidate_a_candidate(tmp_path: Path):
    """Running `next build` is not a change to the candidate."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = tree_fingerprint(tmp_path)
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "chunk.js").write_text("// built", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("// dep", encoding="utf-8")
    assert tree_fingerprint(tmp_path) == before


# ------------------------------------------------------- environment isolation
def test_an_unanswerable_isolation_question_is_not_a_clean_bill(store, tmp_path):
    """No venv means the question cannot be answered, which is not the same as 'fine'."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    runner = _runner(store, tmp_path)
    problems = runner.check_module_isolation(checkout, ("json",))
    assert problems
    assert "could not be determined" in problems[0]


def test_a_module_resolving_into_another_worktree_is_caught(store, tmp_path):
    """Pipewright installs its service packages with `pip install -e`.

    An editable install writes a `.pth` file pointing at the source tree it was
    installed from. A venv carried into a second worktree therefore imports the
    *first* worktree's code, and its tests pass against something that is not
    the candidate. This builds exactly that situation and checks it is caught.
    """
    import subprocess

    other_worktree = tmp_path / "other-worktree"
    (other_worktree / "shared_python").mkdir(parents=True)
    (other_worktree / "shared_python" / "__init__.py").write_text(
        "ORIGIN = 'the other worktree'\n", encoding="utf-8",
    )

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "venv", "--without-pip", str(checkout / ".venv")],
        check=True, capture_output=True,
    )
    site_packages = next((checkout / ".venv" / "lib").glob("python*/site-packages"))
    (site_packages / "_editable_shared_python.pth").write_text(
        f"{other_worktree}\n", encoding="utf-8",
    )

    runner = _runner(store, tmp_path)
    problems = runner.check_module_isolation(checkout, ("shared_python",))
    assert problems, "an editable install pointing at another checkout must be reported"
    assert "outside" in problems[0]
    assert str(other_worktree) in problems[0]
    assert "testing another checkout" in problems[0]


def test_baseline_capture_keeps_a_pre_existing_failure_visible(store, tmp_path):
    runner = _runner(store, tmp_path, (
        _check("was-failing", (sys.executable, "-c", "import sys; sys.exit(1)")),
        _check("was-passing", (sys.executable, "-c", "print('x')")),
    ))
    baseline = runner.capture_baseline(
        ["was-failing", "was-passing"], checkout=tmp_path, candidate_fingerprint="tree:base",
    )
    assert baseline == {"was-failing": Outcome.FAIL, "was-passing": Outcome.PASS}


# ===================== a skip is a gap in coverage, not an absent result ======
def test_a_run_where_nothing_executed_is_a_skip():
    """No case ran, so there is no result, whatever the exit status says."""
    from pw_dev.verify import runner as runner_module

    assert runner_module._pass_count("= 12 skipped in 0.1s =") == 0
    assert runner_module._skip_count("= 12 skipped in 0.1s =") == 12


def test_a_run_with_passes_and_skips_is_a_pass_that_records_the_gap():
    """6,424 cases ran and passed. Calling that "no result" made every gate
    permanently unreachable on any machine without the optional databases,
    which is not a stricter standard -- it is an unusable one.
    """
    from pw_dev.verify import runner as runner_module

    summary = "= 6424 passed, 578 skipped, 21 warnings in 239.69s ="
    assert runner_module._pass_count(summary) == 6424
    assert runner_module._skip_count(summary) == 578


def test_a_failure_is_still_a_failure_even_with_skips():
    from pw_dev.verify import runner as runner_module

    summary = "= 17 failed, 6424 passed, 578 skipped in 239.69s ="
    assert runner_module._skip_count(summary) == 0, (
        "a failure is reported as a failure, never softened into a skip"
    )


def test_a_failure_summary_with_exit_zero_is_still_a_failure(store, tmp_path):
    """The summary is the check's own account. A zero beside it is the lie.

    `os._exit(0)` after a failing run, or a wrapper that swallows the status,
    used to reach the skip/pass branch with failures sitting in the output.
    """
    output = "===== 3 failed, 10 passed in 0.4s ====="
    runner = _runner(store, tmp_path, (
        _check("liar", (sys.executable, "-c", f"print({output!r})")),
    ))
    record = runner.run_check("liar", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.FAIL
    assert "3 failure(s)" in record["detail"]


def test_skipping_more_than_the_baseline_is_not_a_pass(store, tmp_path):
    """The answer to "1 passed, 6000 skipped closes a gate".

    A check may skip what it already skipped before anything changed. Skipping
    *more* means something stopped running during this run, which is coverage
    lost rather than a result earned.
    """
    output = "===== 40 passed, 12 skipped in 1.0s ====="
    runner = _runner(store, tmp_path, (
        _check("budgeted", (sys.executable, "-c", f"print({output!r})")),
    ))
    runner.skip_budget = {"budgeted": 4}
    record = runner.run_check("budgeted", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.SKIP
    assert record["outcome"] not in SUCCESS_OUTCOMES
    assert "baseline of 4" in record["detail"]
    assert "8 stopped running" in record["detail"]


def test_skipping_exactly_the_baseline_still_passes(store, tmp_path):
    """The structural skips of this repository are not a new regression."""
    output = "===== 40 passed, 12 skipped in 1.0s ====="
    runner = _runner(store, tmp_path, (
        _check("budgeted", (sys.executable, "-c", f"print({output!r})")),
    ))
    runner.skip_budget = {"budgeted": 12}
    record = runner.run_check("budgeted", checkout=tmp_path, candidate_fingerprint="tree:x")
    assert record["outcome"] == Outcome.PASS
    assert record["skipped"] == 12


def test_the_baseline_run_adopts_what_it_measured_as_the_budget(store, tmp_path):
    output = "===== 40 passed, 7 skipped in 1.0s ====="
    runner = _runner(store, tmp_path, (
        _check("measured", (sys.executable, "-c", f"print({output!r})")),
    ))
    runner.capture_baseline(["measured"], checkout=tmp_path, candidate_fingerprint="tree:x")
    assert runner.skip_budget["measured"] == 7


def test_verification_scratch_is_outside_the_tree_being_verified(store, tmp_path):
    """Writing temp files into the checkout moved the fingerprint it is bound to."""
    from pw_dev.util.hashing import tree_fingerprint

    checkout = tmp_path / "candidate"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = tree_fingerprint(checkout)

    runner = _runner(store, tmp_path, (
        _check("quiet", (sys.executable, "-c", "print('1 passed')")),
    ))
    scratch = runner.scratch_root(checkout)
    assert checkout not in scratch.parents and scratch != checkout, (
        f"{scratch} is inside the tree under verification"
    )

    runner.run_check("quiet", checkout=checkout, candidate_fingerprint=before)
    assert tree_fingerprint(checkout) == before, (
        "running a check must not change the tree it is describing"
    )
