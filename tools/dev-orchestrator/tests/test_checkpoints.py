"""Verification checkpoints: checks that gate, rather than checks that are noted.

The defect these pin down: a task's declared `verification_ids` were never run
as a condition of anything. The controller ran what the *worker asked for*,
recorded the outcomes as events, integrated the patch and released the
dependents — whatever the outcomes said, and whether or not the worker asked for
anything at all. A plan promising "documentation is updated only after the
verification task passes" was describing an ordering the controller did not
enforce.

A checkpoint is a task with `role: "verification"`. Three properties make it
worth the name, and each has a test here:

* the **controller** chooses what runs, from the accepted specification;
* it runs against the **integrated candidate**, not a worker's checkout;
* only `pass` releases the dependents.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pw_dev.controller.run import Controller
from pw_dev.controller.scheduler import Scheduler, TaskNode
from pw_dev.controller.validate_plan import validate_plan
from pw_dev.errors import PolicyViolation
from pw_dev.state.machine import RunState, TaskState
from pw_dev.testing import (PASSING_EDIT, approval, fake_codex,
                            make_run_config, make_spec, spec_for)
from pw_dev.verify.registry import Registry
from pw_dev.verify.runner import SUCCESS_OUTCOMES
from pw_dev.workspace import git

NON_PASSING = ("fail", "skip", "not_run", "infra_unavailable", "timeout", "error")


# =============================================================== the task type
def test_only_a_verification_task_may_own_nothing():
    verification = TaskNode(id="T-99", title="gate", role="verification",
                            depends_on=[], allowed_paths=[],
                            verification_ids=["fixture:tests"])
    assert verification.is_checkpoint()
    assert verification.is_controller_executed()
    Scheduler([verification], max_parallel=1)  # accepted

    for role in ("backend", "frontend", "contract", "integration", "docs"):
        with pytest.raises(PolicyViolation, match="no writable paths"):
            Scheduler([TaskNode(id="T-01", title="t", role=role, depends_on=[],
                                allowed_paths=[])], max_parallel=1)


def test_a_verification_task_that_owns_files_still_needs_a_worker():
    """Writing the live-acceptance scenario is work; running the checks is not."""
    node = TaskNode(id="T-14", title="prove it", role="verification", depends_on=[],
                    allowed_paths=["scripts/live-acceptance/18-time-travel.json"],
                    verification_ids=["repo:live-acceptance"])
    assert node.is_checkpoint()
    assert not node.is_controller_executed()


def test_an_ordinary_tasks_checks_are_advisory_not_a_gate():
    """A worker asking for `python:service` while it iterates must not thereby
    make that check a completion condition for the phase."""
    node = TaskNode(id="T-02", title="backend", role="backend", depends_on=[],
                    allowed_paths=["services/service-datasets/src/**"],
                    verification_ids=["python:tests"])
    assert not node.is_checkpoint()


def _validate(spec, config):
    return validate_plan(spec, config=config, registry=Registry(),
                         base_commit=spec["base_commit"], repo_root=config.repo_root)


def test_a_plan_may_declare_a_controller_executed_checkpoint(config):
    spec = make_spec(required_verifications=["repo:verify"])
    spec["tasks"].append({
        **copy.deepcopy(spec["tasks"][0]), "id": "T-02", "role": "verification",
        "depends_on": ["T-01"], "allowed_paths": [], "forbidden_paths": [],
        "verification_ids": ["repo:verify"],
    })
    assert _validate(spec, config).ok


def test_a_checkpoint_that_owns_nothing_and_checks_nothing_is_refused(config):
    spec = make_spec()
    spec["tasks"].append({
        **copy.deepcopy(spec["tasks"][0]), "id": "T-02", "role": "verification",
        "depends_on": ["T-01"], "allowed_paths": [], "verification_ids": [],
    })
    report = _validate(spec, config)
    assert any("would do nothing at all" in e for e in report.errors)


@pytest.mark.parametrize("role", ["backend", "frontend", "contract", "integration", "docs"])
def test_an_ordinary_task_owning_nothing_is_still_refused(config, role: str):
    spec = make_spec()
    spec["tasks"][0]["role"] = role
    spec["tasks"][0]["allowed_paths"] = []
    report = _validate(spec, config)
    assert any("cannot produce a patch" in e for e in report.errors)


def test_a_checkpoint_check_outside_required_verifications_is_reported(config):
    """It gates this task's dependents; nothing re-runs it before COMMIT."""
    spec = make_spec(required_verifications=[])
    spec["tasks"].append({
        **copy.deepcopy(spec["tasks"][0]), "id": "T-02", "role": "verification",
        "depends_on": ["T-01"], "allowed_paths": [], "verification_ids": ["repo:smoke"],
    })
    report = _validate(spec, config)
    assert any("nothing re-runs them against the final candidate" in w
               for w in report.warnings)


# ======================================================= what closes a checkpoint
class _StubRunner:
    """A runner whose outcomes the test chooses, so the gate is what is tested."""

    def __init__(self, outcomes: dict[str, str]):
        self.outcomes = outcomes
        self.checkouts: list[Path] = []

    def run_many(self, check_ids, *, checkout, candidate_fingerprint, task_id=None,
                 stop_on_fail=False, cancel_check=None, on_start=None):
        self.checkouts.append(Path(checkout))
        return [{"verification_id": cid, "outcome": self.outcomes.get(cid, "pass")}
                for cid in check_ids if cid in self.outcomes]


def _controller(tmp_path: Path, outcomes: dict[str, str], spec: dict | None = None):
    """A controller with just enough wired to exercise the gate."""
    events: list[tuple] = []
    states: list[tuple] = []

    controller = Controller.__new__(Controller)
    controller.run_id = "run-test"
    controller.spec = spec or make_spec()
    controller.candidate_dir = tmp_path / "candidate"
    controller.candidate_dir.mkdir(parents=True, exist_ok=True)
    (controller.candidate_dir / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    controller.checkpoints = {}
    controller.notes = []
    controller.registry = Registry()
    controller.progress = type("P", (), {"current_check": None, "state": "", "activity": ""})()
    controller._cancelled = type("E", (), {"is_set": lambda self: False})()
    controller.report = lambda line: None
    controller.store = type("Store", (), {
        "event": lambda self, *a, **k: events.append((a, k)),
        "set_task_state": lambda self, *a, **k: states.append((a, k)),
        "usage_summary": lambda self, *a, **k: {},
    })()
    stub = _StubRunner(outcomes)
    controller._verification_runner = lambda: stub
    controller._emit = lambda **kwargs: None
    return controller, stub, events, states


def _node(checks: list[str]) -> TaskNode:
    return TaskNode(id="T-14", title="prove it", role="verification", depends_on=[],
                    allowed_paths=[], verification_ids=checks)


def test_a_passing_checkpoint_records_the_candidate_it_verified(tmp_path: Path):
    controller, stub, events, states = _controller(
        tmp_path, {"fixture:tests": "pass", "fixture:compile": "pass"})
    node = _node(["fixture:tests", "fixture:compile"])

    controller._run_checkpoint(node)

    assert "T-14" in controller.checkpoints
    assert stub.checkouts == [controller.candidate_dir], (
        "a checkpoint verifies the integrated candidate, not a worker's checkout"
    )
    assert any(kind == "checkpoint.passed" for (_, kind, *_), _ in events)


@pytest.mark.parametrize("outcome", NON_PASSING)
def test_no_outcome_other_than_pass_closes_a_checkpoint(tmp_path: Path, outcome: str):
    assert outcome not in SUCCESS_OUTCOMES
    controller, _, _, states = _controller(tmp_path, {"fixture:tests": outcome})
    node = _node(["fixture:tests"])

    with pytest.raises(PolicyViolation) as raised:
        controller._run_checkpoint(node)

    assert f"fixture:tests: {outcome}" in str(raised.value)
    assert "are not released" in str(raised.value)
    assert controller.checkpoints == {}
    assert any(args[2] is TaskState.NEEDS_FIX for args, _ in states)


def test_one_failing_check_among_passing_ones_still_blocks(tmp_path: Path):
    controller, _, _, _ = _controller(
        tmp_path, {"fixture:tests": "pass", "fixture:compile": "fail"})
    with pytest.raises(PolicyViolation, match="fixture:compile: fail"):
        controller._run_checkpoint(_node(["fixture:tests", "fixture:compile"]))


def test_a_check_that_never_executed_blocks_rather_than_passing(tmp_path: Path):
    """Absence of a result is not a result."""
    controller, _, _, _ = _controller(tmp_path, {})  # the runner returns nothing
    with pytest.raises(PolicyViolation, match="never executed"):
        controller._run_checkpoint(_node(["fixture:tests"]))


def test_a_worker_cannot_narrow_a_checkpoint_by_asking_for_less(tmp_path: Path):
    """The checks come from the specification, not from `verification_requests`.

    A worker that requests nothing, or requests only the check it knows passes,
    changes nothing about what the controller runs.
    """
    controller, stub, _, _ = _controller(
        tmp_path, {"fixture:tests": "pass", "fixture:compile": "fail"})
    node = _node(["fixture:tests", "fixture:compile"])

    with pytest.raises(PolicyViolation, match="fixture:compile"):
        controller._run_checkpoint(node)


def test_a_checkpoints_accepted_preexisting_failures_do_not_apply(tmp_path: Path):
    """That mechanism is for a check the phase inherited broken.

    A checkpoint is a statement about this phase's own work, so scoping one out
    would waive the thing it exists to assert.
    """
    spec = make_spec(accepted_preexisting_failures=[
        {"verification_id": "fixture:tests", "reason": "was already failing"}])
    controller, _, _, _ = _controller(tmp_path, {"fixture:tests": "fail"}, spec=spec)
    with pytest.raises(PolicyViolation, match="fixture:tests: fail"):
        controller._run_checkpoint(_node(["fixture:tests"]))


def test_a_checkpoint_naming_no_checks_gates_nothing_and_says_so(tmp_path: Path):
    controller, _, events, _ = _controller(tmp_path, {})
    controller._run_checkpoint(_node([]))
    assert any(kind == "checkpoint.empty" for (_, kind, *_), _ in events)


def test_changed_candidate_content_invalidates_a_passing_checkpoint(tmp_path: Path):
    """A pass describes one tree. Anything integrated after it describes another."""
    controller, _, _, _ = _controller(tmp_path, {"fixture:tests": "pass"})
    controller._run_checkpoint(_node(["fixture:tests"]))
    assert controller._stale_checkpoints() == []

    (controller.candidate_dir / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert controller._stale_checkpoints() == ["T-14"], (
        "a resumed run must recheck a checkpoint whose candidate moved on"
    )


def test_dependents_are_named_in_the_refusal(tmp_path: Path):
    spec = make_spec()
    spec["tasks"].append({
        **copy.deepcopy(spec["tasks"][0]), "id": "T-14", "role": "verification",
        "allowed_paths": [], "depends_on": ["T-01"], "verification_ids": ["fixture:tests"],
    })
    spec["tasks"].append({
        **copy.deepcopy(spec["tasks"][0]), "id": "T-15", "role": "docs",
        "allowed_paths": ["docs/HANDOFF.md"], "depends_on": ["T-14"],
    })
    controller, _, _, _ = _controller(tmp_path, {"fixture:tests": "fail"}, spec=spec)
    with pytest.raises(PolicyViolation, match="T-15"):
        controller._run_checkpoint(_node(["fixture:tests"]))


# ============================================================ end to end, for real
def _checkpoint_spec(base: str, *, broken: bool) -> dict:
    """T-01 writes code, T-02 is a checkpoint, T-03 documents the result."""
    spec = spec_for(base)
    spec["required_verifications"] = ["fixture:tests"]
    spec["tasks"] = [
        {
            "id": "T-01", "title": "implement", "role": "backend",
            "objective": "set VALUE", "depends_on": [], "requirement_ids": ["R-01"],
            "allowed_paths": ["src/app.py", "tests/**"], "forbidden_paths": [],
            "exclusive_resources": [], "acceptance_criteria": ["VALUE is 2"],
            "verification_ids": [], "context_paths": [], "notes": None,
        },
        {
            "id": "T-02", "title": "checkpoint", "role": "verification",
            "objective": "prove the tests pass on the integrated candidate",
            "depends_on": ["T-01"], "requirement_ids": ["R-01"],
            "allowed_paths": [], "forbidden_paths": [], "exclusive_resources": [],
            "acceptance_criteria": ["the suite passes"],
            "verification_ids": ["fixture:tests"], "context_paths": [], "notes": None,
        },
        {
            "id": "T-03", "title": "record it", "role": "docs",
            "objective": "write the ledger entry", "depends_on": ["T-02"],
            "requirement_ids": ["R-01"], "allowed_paths": ["docs/DONE.md"],
            "forbidden_paths": [], "exclusive_resources": [],
            "acceptance_criteria": ["the ledger says so"], "verification_ids": [],
            "context_paths": [], "notes": None,
        },
    ]
    return spec


#: `VALUE` is 2 and the test asserts 3, so `fixture:tests` fails on the
#: integrated candidate — which is the only way to find out whether a
#: checkpoint actually gates anything.
BROKEN_TEST = ("import unittest\n\nfrom src.app import VALUE\n\n\n"
               "class ValueTest(unittest.TestCase):\n"
               "    def test_value(self):\n"
               "        self.assertEqual(VALUE, 3)\n")


def fake_claude_per_task(bin_dir: Path, per_task: dict[str, dict[str, str]]) -> Path:
    """A worker that writes what *its own* task owns.

    `fake_claude` writes every edit on every call, which is fine for a
    single-task run and would make every task here write another task's files.
    This one reads the task id out of the assignment it was handed, exactly as a
    real worker would, and writes only that task's edits.
    """
    from pw_dev.testing import install_stub

    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "claude-calls.json"
    body = f'''
import json, sys, os, pathlib, re
argv = sys.argv[1:]
log = pathlib.Path({str(log)!r})
calls = json.loads(log.read_text()) if log.exists() else []
prompt = argv[-1]
found = re.search(r"`task_id` set to `([^`]+)`", prompt)
task_id = found.group(1) if found else "T-01"
calls.append({{"cwd": os.getcwd(), "task_id": task_id}})
log.write_text(json.dumps(calls))

per_task = json.loads({json.dumps(json.dumps(per_task))})
here = pathlib.Path(os.getcwd())
for name, content in per_task.get(task_id, {{}}).items():
    target = here / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)

report = {{
    "schema_version": "worker_report/v1", "task_id": task_id, "status": "completed",
    "summary": "done", "changed_paths": sorted(per_task.get(task_id, {{}})),
    "requirement_ids_addressed": ["R-01"], "tests_claimed": [],
    "verification_requests": [], "assumptions": [], "blockers": [],
    "proposed_improvements": [],
}}
text = json.dumps(report) if "--json-schema" in argv else "ok"
print(json.dumps({{
    "type": "result", "subtype": "success", "is_error": False, "duration_ms": 10,
    "num_turns": 1, "result": text, "session_id": "s-1", "total_cost_usd": 0.01,
    "usage": {{"input_tokens": 500, "output_tokens": 50, "cache_read_input_tokens": 0}},
    "modelUsage": {{"claude-sonnet-5": {{"outputTokens": 50}}}},
    "permission_denials": [], "terminal_reason": "completed",
}}))
'''
    return install_stub(bin_dir / "claude", body)


def _run(fixture_repo: Path, tmp_path: Path, *, broken: bool):
    from pw_dev.state.db import RunStore

    base = git.head_sha(fixture_repo)
    spec = _checkpoint_spec(base, broken=broken)
    bin_dir = tmp_path / "bin"
    per_task = {
        "T-01": {
            "src/app.py": "VALUE = 2\n",
            "tests/test_app.py": BROKEN_TEST if broken
            else PASSING_EDIT["tests/test_app.py"]["fixed"],
        },
        "T-03": {"docs/DONE.md": "# Phase recorded\n"},
    }
    claude = fake_claude_per_task(bin_dir, per_task)
    codex = fake_codex(bin_dir, {"planner": spec, "reviewer": approval(
        spec, "PLACEHOLDER", "PLACEHOLDER")})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        state = controller.execute(imported_spec=spec)
    finally:
        controller.release()
    return state, run_id, store, bin_dir


def test_a_failing_checkpoint_blocks_the_documentation_task(fixture_repo: Path,
                                                            tmp_path: Path):
    """The ordering the plan promises, enforced rather than described."""
    state, run_id, store, bin_dir = _run(fixture_repo, tmp_path, broken=True)

    assert state is RunState.BLOCKED
    detail = store.get_run(run_id)["state_detail"]
    assert "T-02" in detail and "checkpoint" in detail
    assert "T-03" in detail, "the refusal names the dependents it is holding back"

    tasks = {row["task_id"]: row["state"] for row in store.get_tasks(run_id)}
    assert tasks["T-01"] == TaskState.INTEGRATED.value
    assert tasks["T-02"] == TaskState.NEEDS_FIX.value
    assert tasks["T-03"] == TaskState.PENDING.value, (
        "documentation must not run behind a checkpoint that did not pass"
    )

    calls = json.loads((bin_dir / "claude-calls.json").read_text(encoding="utf-8"))
    assert [c["task_id"] for c in calls] == ["T-01"], (
        "only T-01 was dispatched: the checkpoint needs no worker and T-03 never "
        "became eligible"
    )
    store.close()


def test_a_passing_checkpoint_releases_the_documentation_task(fixture_repo: Path,
                                                              tmp_path: Path):
    state, run_id, store, bin_dir = _run(fixture_repo, tmp_path, broken=False)

    assert state is RunState.VERIFIED_LOCAL, store.get_run(run_id)["state_detail"]
    tasks = {row["task_id"]: row["state"] for row in store.get_tasks(run_id)}
    assert tasks["T-02"] == TaskState.INTEGRATED.value
    assert tasks["T-03"] == TaskState.INTEGRATED.value

    events = [e["message"] for e in store.events(run_id)]
    assert any("passed against candidate" in message for message in events)

    calls = json.loads((bin_dir / "claude-calls.json").read_text(encoding="utf-8"))
    assert sorted(c["task_id"] for c in calls) == ["T-01", "T-03"], (
        "T-01 and T-03 have workers; the checkpoint does not"
    )
    store.close()


def test_the_final_gates_still_run_after_the_checkpoint(fixture_repo: Path,
                                                        tmp_path: Path):
    """A checkpoint partway through does not replace the gate before COMMIT."""
    state, run_id, store, _ = _run(fixture_repo, tmp_path, broken=False)
    assert state is RunState.VERIFIED_LOCAL

    evidence = store.evidence_for(run_id)
    by_check: dict[str, list[str]] = {}
    for record in evidence:
        by_check.setdefault(record["verification_id"], []).append(record["outcome"])

    assert "fixture:tests" in by_check
    assert len(by_check["fixture:tests"]) >= 2, (
        "the checkpoint runs it, and the final gate runs it again on the finished "
        "candidate"
    )
    assert "fixture:compile" in by_check, "profile gates are unaffected by checkpoints"
    store.close()


# ============================================ budgets: what the numbers mean
def test_a_dependency_chain_is_not_divided_by_the_worker_count(config):
    """`ceil(tasks / workers) x timeout` is not a ceiling when tasks are chained.

    Five chained tasks with three workers still run one after another. The old
    arithmetic said two rounds, which understated the real requirement by three
    -- the dangerous direction for something described as an upper bound.
    """
    spec = make_spec()
    base = spec["tasks"][0]
    spec["tasks"] = [
        {**copy.deepcopy(base), "id": f"T-{i:02d}", "allowed_paths": [f"src/m{i}.py"],
         "depends_on": ([f"T-{i - 1:02d}"] if i > 1 else [])}
        for i in range(1, 6)
    ]
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 1800,
                               "total_run_seconds": 3600, "repair_rounds_per_task": 2}
    report = _validate(spec, config)

    error = next((e for e in report.errors if "cannot overlap" in e), None)
    assert error, report.render()
    assert "dependency chain of 5 worker task(s)" in error
    assert "T-01 -> T-02 -> T-03 -> T-04 -> T-05" in error
    assert "9000s" in error, "5 chained tasks x 1800s, not ceil(5/2) x 1800s"
    assert "PAUSED with the work preserved" in error


def test_tasks_serialized_by_one_resource_are_counted(config):
    """An exclusive resource serializes its holders whatever the graph says."""
    spec = make_spec()
    base = spec["tasks"][0]
    spec["tasks"] = [
        {**copy.deepcopy(base), "id": f"T-{i:02d}", "allowed_paths": [f"src/m{i}.py"],
         "depends_on": [], "exclusive_resources": ["alembic"]}
        for i in range(1, 6)
    ]
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 1800,
                               "total_run_seconds": 3600, "repair_rounds_per_task": 2}
    report = _validate(spec, config)
    error = next((e for e in report.errors if "cannot overlap" in e), None)
    assert error and "serialized on the 'alembic' resource" in error


def test_worker_capacity_alone_can_exceed_the_budget(config):
    """No chain and no shared lock, and two workers still need six waves."""
    spec = make_spec()
    base = spec["tasks"][0]
    spec["tasks"] = [
        {**copy.deepcopy(base), "id": f"T-{i:02d}", "allowed_paths": [f"src/m{i}.py"],
         "depends_on": []}
        for i in range(1, 13)
    ]
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 30,
                               "total_run_seconds": 60, "repair_rounds_per_task": 2}
    report = _validate(spec, config)
    error = next((e for e in report.errors if "cannot overlap" in e), None)
    assert error, "worker capacity alone forces six waves"
    assert "6 wave(s)" in error


def test_the_arithmetic_names_what_it_excludes(config):
    spec = make_spec()
    base = spec["tasks"][0]
    spec["tasks"] = [
        {**copy.deepcopy(base), "id": f"T-{i:02d}", "allowed_paths": [f"src/m{i}.py"],
         "depends_on": ([f"T-{i - 1:02d}"] if i > 1 else [])}
        for i in range(1, 4)
    ]
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 1800,
                               "total_run_seconds": 7200, "repair_rounds_per_task": 2}
    report = _validate(spec, config)
    warning = next((w for w in report.warnings
                    if "largest unavoidable serialization" in w), None)
    assert warning
    assert "environment preparation" in warning
    assert "worst case, not a prediction" in warning


def test_the_longest_chain_is_the_longest_not_the_first():
    from pw_dev.controller.validate_plan import _longest_chain

    spec = make_spec()
    base = spec["tasks"][0]
    # T-04 joins a short branch and a long one; the long one decides.
    spec["tasks"] = [
        {**copy.deepcopy(base), "id": "T-01", "depends_on": [], "allowed_paths": ["a.py"]},
        {**copy.deepcopy(base), "id": "T-02", "depends_on": ["T-01"],
         "allowed_paths": ["b.py"]},
        {**copy.deepcopy(base), "id": "T-03", "depends_on": ["T-02"],
         "allowed_paths": ["c.py"]},
        {**copy.deepcopy(base), "id": "T-09", "depends_on": [], "allowed_paths": ["d.py"]},
        {**copy.deepcopy(base), "id": "T-04", "depends_on": ["T-03", "T-09"],
         "allowed_paths": ["e.py"]},
    ]
    length, path = _longest_chain(spec)
    assert length == 4
    assert path == ["T-01", "T-02", "T-03", "T-04"]


# ============ stale evidence: the fingerprint has to see what changed
def test_a_symlink_change_invalidates_a_passing_checkpoint(tmp_path: Path):
    """`tree_fingerprint` skipped symlinks entirely.

    A checkpoint passed, a later task added or repointed a symlink, the run
    paused, and the resumed candidate hashed identically — so the earlier pass
    was inherited although the candidate had moved.
    """
    import os

    controller, _, _, _ = _controller(tmp_path, {"fixture:tests": "pass"})
    controller._run_checkpoint(_node(["fixture:tests"]))
    assert controller._stale_checkpoints() == []

    os.symlink("/etc/hosts", controller.candidate_dir / "added-link")
    assert controller._stale_checkpoints() == ["T-14"], (
        "adding a symlink is a change to the candidate"
    )

    os.remove(controller.candidate_dir / "added-link")
    assert controller._stale_checkpoints() == []
    os.symlink("/etc/hosts", controller.candidate_dir / "added-link")
    os.remove(controller.candidate_dir / "added-link")
    os.symlink("/tmp", controller.candidate_dir / "added-link")
    assert controller._stale_checkpoints() == ["T-14"], (
        "repointing a symlink is a change to the candidate"
    )


def test_a_controller_supplied_dependency_directory_is_not_a_candidate_change(
        tmp_path: Path):
    """`node_modules` and `.venv` are the controller's doing, not the work's."""
    controller, _, _, _ = _controller(tmp_path, {"fixture:tests": "pass"})
    controller._run_checkpoint(_node(["fixture:tests"]))

    (controller.candidate_dir / "node_modules").mkdir()
    (controller.candidate_dir / ".venv").mkdir()
    assert controller._stale_checkpoints() == []


# ================== a command that ends quietly has not proved it ran
def test_exit_zero_without_the_output_a_check_produces_is_not_a_pass(
        store, tmp_path: Path):
    """`os._exit(0)` from anything the check imported looks exactly like success.

    Verification runs the code the phase is writing -- that is what verification
    is -- so the defence is not to stop it running but to stop silence counting
    as a result.
    """
    from pw_dev.verify.registry import Check, Registry
    from pw_dev.verify.runner import VerificationRunner

    quiet = Check(
        id="fixture:quiet",
        description="a check that exits zero and says nothing",
        argv=("python3", "-c", "import os; os._exit(0)"),
        timeout_seconds=60,
        success_pattern=r"\d+ (?:passed|failed)",
    )
    loud = Check(
        id="fixture:loud",
        description="a check that says what it did",
        argv=("python3", "-c", "print('3 passed')"),
        timeout_seconds=60,
        success_pattern=r"\d+ (?:passed|failed)",
    )
    registry = Registry((quiet, loud))
    run_id = store.create_run(brain="automatic", config_snapshot={},
                              publication_mode="none", deadline_epoch=None, plan_only=True)
    runner = VerificationRunner(registry, store=store, run_id=run_id,
                                base_commit="0" * 40, spec_digest="d",
                                artifacts_dir=tmp_path / "ev")

    silent = runner.run_check("fixture:quiet", checkout=tmp_path,
                              candidate_fingerprint="f")
    assert silent["exit_status"] == 0
    assert silent["outcome"] == "error", "exit zero is not evidence on its own"
    assert "has not demonstrated that it ran" in silent["detail"]

    spoke = runner.run_check("fixture:loud", checkout=tmp_path,
                             candidate_fingerprint="f")
    assert spoke["outcome"] == "pass"


def test_the_repository_test_checks_require_their_own_summary():
    from pw_dev.verify.registry import Registry

    registry = Registry()
    for check_id in ("python:tests", "python:service", "orchestrator:tests",
                     "repo:verify"):
        assert registry.get(check_id).success_pattern, (
            f"{check_id} runs pytest; a run with no summary did not finish"
        )


def test_a_process_left_behind_by_a_finished_command_is_reaped():
    """A command whose main process exits normally can leave a child holding on.

    Terminating only on timeout and cancellation left it running -- and a worker
    that wanted one would arrange exactly that, then have it wait for the
    environment rebuild and edit the interpreter before checks ran.
    """
    import sys
    import tempfile
    import time

    from pw_dev.util import proc

    with tempfile.TemporaryDirectory() as raw:
        marker = Path(raw) / "still-alive"
        # The child records *its own pid*. Asking the kernel whether that exact
        # process is alive is a more precise question than scanning `ps` output
        # for a string -- and `ps` is setuid root, which a sandboxed check
        # cannot execute at all, so a test that depended on it could not run
        # under the confinement verification now uses.
        script = (
            f"import subprocess, sys, os\n"
            f"subprocess.Popen([sys.executable, '-c',"
            f" \"import time, pathlib, os;\"\n"
            f"  \"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));\"\n"
            f"  \"time.sleep(120)\"],\n"
            f" stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            f"raise SystemExit(0)\n"
        )
        result = proc.run([sys.executable, "-c", script], cwd=Path(raw),
                          env=proc.build_env(), timeout=60,
                          max_output_bytes=1 << 20)
        assert result.returncode == 0
        assert not result.timed_out and not result.cancelled

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.1)
        if not marker.exists():
            import pytest as _pytest

            _pytest.skip("the detached child never started; nothing to reap")

        stray = int(marker.read_text(encoding="utf-8").strip())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _alive(stray):
            time.sleep(0.1)
        assert not _alive(stray), (
            f"pid {stray} outlived the run that created it; the group must be reaped"
        )


def _alive(pid: int) -> bool:
    """Whether a process still exists, asked of the kernel directly.

    `os.kill(pid, 0)` performs the permission and existence check without
    sending anything. `ProcessLookupError` is the answer we are looking for;
    `PermissionError` means it exists and belongs to somebody else, which for
    this purpose still counts as alive.
    """
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_a_pass_measured_against_another_tree_does_not_complete_the_run(config, store):
    """Evidence names the tree it ran against; completion compares the two.

    A check that passed and then saw the candidate change has not shown that the
    approved tree passes. `.git` and `.venv` are outside the fingerprint, so
    without this comparison a mutation there would leave nothing to notice.
    """
    from pw_dev.controller.run import Controller

    controller = object.__new__(Controller)
    controller.spec = {"required_verifications": ["repo:verify"],
                       "accepted_preexisting_failures": []}
    controller.registry = config_registry(config)
    controller.final_records = {
        "repo:verify": {"outcome": "pass", "candidate_fingerprint": "tree:OLD"},
    }
    mismatched = controller._evidence_not_describing("tree:APPROVED")
    assert any("repo:verify" in entry for entry in mismatched)
    assert "tree:OLD" in mismatched[0]

    controller.final_records["repo:verify"]["candidate_fingerprint"] = "tree:APPROVED"
    assert controller._evidence_not_describing("tree:APPROVED") == []


def config_registry(config):
    from pw_dev.verify.registry import registry_for
    return registry_for(config.verification_profile)


def test_a_partial_baseline_is_measured_again_rather_than_half_believed(
        tmp_path, config, store):
    """A gate with no recorded outcome read as "was already failing".

    That is the state a waiver is available from, so a partial artifact was
    worse than none: the run did not recapture, and a gate that had never been
    measured became scopeable.
    """
    from pw_dev.controller.run import Controller

    controller = object.__new__(Controller)
    controller.spec = {"required_verifications": [], "accepted_preexisting_failures": []}
    controller.registry = config_registry(config)
    controller.notes = []
    controller.baseline = {}
    controller.skip_budget = {}
    controller.run_id = "run-x"

    gates = controller.gate_checks()
    artifact = tmp_path / "baseline.json"

    class _Store:
        def latest_artifact(self, run_id, name):
            return {"path": str(artifact)}

    controller.store = _Store()

    # complete: restored
    artifact.write_text(json.dumps({
        "version": 2,
        "outcomes": {cid: "pass" for cid in gates},
        "skips": {cid: 0 for cid in gates},
    }), encoding="utf-8")
    controller._restore_baseline()
    assert controller.baseline and controller.skip_budget

    # one outcome missing: not restored, so the run measures again
    controller.baseline, controller.skip_budget, controller.notes = {}, {}, []
    partial = {cid: "pass" for cid in gates}
    partial.pop(gates[0])
    artifact.write_text(json.dumps({
        "version": 2, "outcomes": partial, "skips": {cid: 0 for cid in gates},
    }), encoding="utf-8")
    controller._restore_baseline()
    assert controller.baseline == {} and controller.skip_budget == {}
    assert any("incomplete" in note for note in controller.notes)

    # a nonsense skip count: also measured again
    controller.baseline, controller.skip_budget, controller.notes = {}, {}, []
    artifact.write_text(json.dumps({
        "version": 2,
        "outcomes": {cid: "pass" for cid in gates},
        "skips": {cid: (-1 if cid == gates[0] else 0) for cid in gates},
    }), encoding="utf-8")
    controller._restore_baseline()
    assert controller.baseline == {}
