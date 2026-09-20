"""Crash recovery, budgets, parallelism in practice, and the interactive boundaries."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path


from pw_dev.controller.recovery import reconcile
from pw_dev.controller.run import Controller
from pw_dev.controller.scheduler import Scheduler, TaskNode
from pw_dev.state.db import RunStore
from pw_dev.state.machine import RunState, TaskState
from pw_dev.util.hashing import tree_fingerprint
from pw_dev.workspace import git
from pw_dev.testing import (PASSING_EDIT, approval, fake_claude, fake_codex,
                            make_run_config, spec_for)


# --------------------------------------------------------------- recovery
def test_a_live_controller_blocks_a_second_one(fixture_repo: Path, tmp_path: Path):
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.acquire_run_lock(run_id)

    report = reconcile(config, store, run_id)
    assert not report.resumable
    assert "still owns this run" in report.blocked_reason
    assert "dispatch the same task twice" in report.blocked_reason
    store.close()


def test_a_crashed_controller_is_reclaimed_and_partial_work_is_noticed(
    fixture_repo: Path, tmp_path: Path,
):
    """A killed worker may have written half its changes. Never assume it did nothing."""
    import os
    import sys

    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    base = git.head_sha(fixture_repo)
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.update_run_fields(run_id, base_commit=base)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "backend"}])

    # A worktree with half-finished work, and a lease from a process that is gone.
    from pw_dev.workspace.worktrees import WorktreeManager

    manager = WorktreeManager(fixture_repo, config.runs_dir() / run_id, run_id)
    worktree = manager.create("T-01", base_commit=base)
    (worktree.path / "src" / "app.py").write_text("VALUE = 2  # half done\n", encoding="utf-8")
    store.set_task_state(run_id, "T-01", TaskState.RUNNING, "working",
                         worktree=str(worktree.path))

    dead = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    dead.wait()
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO run_locks(run_id, owner_pid, owner_token, hostname, acquired_at,"
            " heartbeat_at) VALUES(?,?,?,?,?,?)",
            (run_id, dead.pid, "stale", os.uname().nodename, "t", "t"),
        )
        conn.execute(
            "INSERT INTO leases(run_id, task_id, lease_token, owner_pid, child_pid,"
            " acquired_at, heartbeat_at, expires_at_epoch) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, "T-01", "t", dead.pid, None, "t", "t", time.time() - 1),
        )

    report = reconcile(config, store, run_id)
    assert report.resumable
    assert any("reclaimed" in a for a in report.actions)
    assert any("did not do nothing" in o for o in report.observations)
    assert any("re-run from a fresh checkout" in a for a in report.actions)
    assert store.get_task(run_id, "T-01")["state"] == TaskState.PENDING.value

    manager.cleanup()
    manager.prune_branches()
    store.close()


def test_a_run_that_crashed_after_pushing_is_not_published_twice(
    fixture_repo: Path, bare_remote: Path, tmp_path: Path,
):
    """Recovery asks the remote, not our own record — the record is what may be missing."""
    base = git.head_sha(fixture_repo)
    spec = spec_for(base, publication_policy={"mode": "feature_branch",
                                              "branch_prefix": "pw-dev",
                                              "allow_existing_branch": None})
    bin_dir = tmp_path / "bin"
    claude = fake_claude(bin_dir, edits=PASSING_EDIT)
    codex = fake_codex(bin_dir, {"planner": spec,
                                 "reviewer": approval(spec, "PLACEHOLDER", "PLACEHOLDER")})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="feature_branch")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="feature_branch", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        state = controller.execute(imported_spec=spec)
    finally:
        controller.release()
    assert state is RunState.COMPLETE

    receipt = json.loads(
        (config.runs_dir() / run_id / "publication-receipt.json").read_text(encoding="utf-8")
    )
    # Simulate the controller dying before it recorded COMPLETE.
    store.set_run_state(run_id, RunState.PUSH, "pretending the crash happened here", force=True)

    report = reconcile(config, store, run_id)
    assert any("already points at" in o for o in report.observations)
    assert any("must not push again" in o for o in report.observations)
    assert store.get_run(run_id)["state"] == RunState.COMPLETE.value, (
        "reconciliation must recognise the run was already published"
    )

    on_remote = subprocess.run(  # noqa: S603
        ["git", "rev-list", "--count", f"refs/heads/{receipt['branch']}", f"^{base}"],
        cwd=bare_remote, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert on_remote == "1", "exactly one commit was published, not two"
    store.close()


def test_a_run_that_crashed_before_committing_has_nothing_published(
    fixture_repo: Path, bare_remote: Path, tmp_path: Path,
):
    base = git.head_sha(fixture_repo)
    spec = spec_for(base)
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {"planner": spec}),
                             fake_claude(bin_dir, edits=PASSING_EDIT), mode="feature_branch")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="feature_branch", deadline_epoch=None)
    store.update_run_fields(run_id, base_commit=base)

    from pw_dev.workspace import git as gitmod

    candidate = config.runs_dir() / run_id / "candidate"
    gitmod.add_worktree(fixture_repo, candidate, base, f"pw-dev/{run_id}/candidate")
    store.set_run_state(run_id, RunState.PLAN, "x", force=True)
    store.set_run_state(run_id, RunState.COMMIT, "crashed here", force=True)

    report = reconcile(config, store, run_id)
    assert any("no commit was created locally" in o for o in report.observations)
    assert store.get_run(run_id)["state"] == RunState.COMMIT.value

    gitmod.remove_worktree(fixture_repo, candidate)
    store.close()


def test_a_candidate_that_changed_since_the_recorded_fingerprint_invalidates_approval(
    fixture_repo: Path, tmp_path: Path,
):
    base = git.head_sha(fixture_repo)
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.update_run_fields(run_id, base_commit=base)

    candidate = config.runs_dir() / run_id / "candidate"
    git.add_worktree(fixture_repo, candidate, base, f"pw-dev/{run_id}/candidate")
    recorded = tree_fingerprint(candidate)
    store.update_run_fields(run_id, candidate_fingerprint=recorded,
                            approved_fingerprint=recorded)

    (candidate / "src" / "app.py").write_text("VALUE = 42\n", encoding="utf-8")
    report = reconcile(config, store, run_id)
    assert any("invalidated" in a for a in report.actions)
    assert store.get_run(run_id)["approved_fingerprint"] is None

    git.remove_worktree(fixture_repo, candidate)
    store.close()


# ------------------------------------------------------------------- limits
def test_an_exhausted_run_budget_pauses_with_work_preserved(fixture_repo: Path, tmp_path: Path):
    base = git.head_sha(fixture_repo)
    # A schedulable plan with an ordinary budget: a zero-second budget is not a
    # budget, and plan validation refuses it as unschedulable before any of this
    # happens. What is simulated here is a run whose wall clock ran out while it
    # was working, so the controller is handed a deadline that has already passed.
    spec = spec_for(base, resource_limits={"max_parallel_workers": 2,
                                           "per_task_seconds": 60,
                                           "total_run_seconds": 600,
                                           "repair_rounds_per_task": 2})
    bin_dir = tmp_path / "bin"
    codex = fake_codex(bin_dir, {"planner": spec})
    claude = fake_claude(bin_dir, edits=PASSING_EDIT)
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller._deadline = time.monotonic() - 1
    controller.acquire()
    try:
        state = controller.execute(imported_spec=spec)
    finally:
        controller.release()

    assert state is RunState.PAUSED, "an exhausted budget pauses; it never completes"
    detail = store.get_run(run_id)["state_detail"]
    assert "resume" in detail
    assert "not a completed phase" in detail
    store.close()


def test_a_repair_loop_that_makes_no_progress_escalates(fixture_repo: Path, tmp_path: Path):
    """Identical failures round after round is a wall, not progress."""
    base = git.head_sha(fixture_repo)
    spec = spec_for(base, required_verifications=["fixture:tests"])
    bin_dir = tmp_path / "bin"
    # A worker that never fixes the test it broke.
    claude = fake_claude(bin_dir, edits={
        "src/app.py": {"fixed": "VALUE = 2\n"},   # the fixture test still expects 1
    })
    codex = fake_codex(bin_dir, {"planner": spec})
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

    assert state is RunState.PAUSED
    detail = store.get_run(run_id)["state_detail"]
    assert "identical failure set" in detail or "still failing after" in detail
    assert "not a completed phase" in detail

    evidence = store.evidence_for(run_id)
    assert any(e["verification_id"] == "fixture:tests" and e["outcome"] == "fail"
               for e in evidence), "the failing check is recorded, not hidden"
    store.close()


def test_cancellation_preserves_work(fixture_repo: Path, tmp_path: Path):
    base = git.head_sha(fixture_repo)
    spec = spec_for(base)
    bin_dir = tmp_path / "bin"
    codex = fake_codex(bin_dir, {"planner": spec})
    claude = fake_claude(bin_dir, edits=PASSING_EDIT)
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.cancel()
    controller.acquire()
    try:
        state = controller.execute(imported_spec=spec)
    finally:
        controller.release()

    assert state is RunState.CANCELLED
    assert "cancelled" in store.get_run(run_id)["state_detail"]
    store.close()


# ------------------------------------------------------------- parallelism
def test_bounded_parallelism_holds_under_a_real_dispatch_loop():
    """The limit is what actually constrains concurrency, not a comment."""
    nodes = [TaskNode(id=f"T-{i:02d}", title="t", role="backend", depends_on=[],
                      allowed_paths=[f"services/s{i}/**"]) for i in range(1, 10)]
    scheduler = Scheduler(nodes, max_parallel=3)

    done: set[str] = set()
    running: set[str] = set()
    peak = 0
    lock = threading.Lock()

    def work(task_id: str) -> None:
        nonlocal peak
        with lock:
            running.add(task_id)
            peak = max(peak, len(running))
        time.sleep(0.02)
        with lock:
            running.discard(task_id)
            done.add(task_id)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        while len(done) < len(nodes):
            with lock:
                ready = scheduler.ready(done=set(done), running=set(running),
                                        held_resources={})
            for node in ready:
                with lock:
                    running.add(node.id)
                futures.append(pool.submit(work, node.id))
            time.sleep(0.005)
        concurrent.futures.wait(futures)

    assert peak <= 3, f"concurrency reached {peak}, above the configured limit of 3"
    assert done == {n.id for n in nodes}


# ------------------------------------------------------- interactive brain
def test_an_interactive_run_exports_review_evidence_and_waits(
    fixture_repo: Path, tmp_path: Path,
):
    base = git.head_sha(fixture_repo)
    spec = spec_for(base)
    bin_dir = tmp_path / "bin"
    claude = fake_claude(bin_dir, edits=PASSING_EDIT)
    codex = fake_codex(bin_dir, {})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="interactive", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="interactive",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        state = controller.execute(imported_spec=spec)
    finally:
        controller.release()

    assert state is RunState.WAITING_FOR_REVIEW
    packet = json.loads(
        (config.runs_dir() / run_id / "review-request.json").read_text(encoding="utf-8")
    )
    assert packet["candidate_fingerprint"]
    assert packet["diff"]
    assert packet["evidence"], "the reviewer receives independently recorded evidence"
    assert packet["schema"] == "review_findings/v1"
    assert not (bin_dir / "codex-calls.json").exists(), (
        "the interactive brain does not call the reviewer CLI"
    )
    store.close()


def test_an_imported_review_for_the_wrong_candidate_is_refused(
    fixture_repo: Path, tmp_path: Path,
):
    """Imported approval is accepted only through the trusted interface, bound to this tree."""
    from pw_dev.cli import main

    base = git.head_sha(fixture_repo)
    spec = spec_for(base)
    bin_dir = tmp_path / "bin"
    # `pw-dev` resolves its own state directory from the repository, so the run
    # has to live where the CLI will look for it.
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits=PASSING_EDIT), mode="none",
                             state_dir=fixture_repo / ".pw-dev")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="interactive", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="interactive",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        controller.execute(imported_spec=spec)
    finally:
        controller.release()
    store.close()

    stale = approval(spec, run_id, "tree:" + "0" * 64)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(stale), encoding="utf-8")

    # The CLI resolves its own config, so point it at this repository.
    code = main(["--repo", str(fixture_repo), "review-import", run_id, str(path)])
    assert code == 2, "a review of a different tree must be refused"

    with RunStore(config.db_path(), config.runs_dir()) as reopened:
        assert reopened.get_run(run_id)["approved_fingerprint"] is None


# --------------------------------------------------------------------- resume
def test_a_resumed_run_does_not_re_run_integrated_tasks(fixture_repo: Path, tmp_path: Path):
    """Resumption continues; it does not start over.

    The run is paused after its task is integrated. Resuming must reuse that
    work — re-dispatching it would spend a second worker on something that
    already succeeded, and would discard the candidate it produced.
    """
    base = git.head_sha(fixture_repo)
    spec = spec_for(base)
    bin_dir = tmp_path / "bin"
    claude = fake_claude(bin_dir, edits=PASSING_EDIT)
    codex = fake_codex(bin_dir, {"planner": spec,
                                 "reviewer": approval(spec, "PLACEHOLDER", "PLACEHOLDER")})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    first = Controller(config, store=store, run_id=run_id, brain="automatic",
                       reporter=lambda line: None)
    first.acquire()
    try:
        first.discover()
        first.validate(spec)
        first.implement()
    finally:
        first.release()

    assert store.get_task(run_id, "T-01")["state"] == TaskState.INTEGRATED.value
    store.set_run_state(run_id, RunState.PAUSED, "pretending a limit was reached", force=True)
    worker_calls_before = len(json.loads((bin_dir / "claude-calls.json").read_text()))

    second = Controller(config, store=store, run_id=run_id, brain="automatic",
                        reporter=lambda line: None)
    second.acquire()
    try:
        state = second.resume()
    finally:
        second.release()

    assert state is RunState.VERIFIED_LOCAL, store.get_run(run_id)["state_detail"]
    worker_calls_after = len(json.loads((bin_dir / "claude-calls.json").read_text()))
    assert worker_calls_after == worker_calls_before, (
        "the integrated task was re-dispatched instead of being reused"
    )
    events = [e["message"] for e in store.events(run_id)]
    assert any("already integrated and are not re-run" in e for e in events)
    store.close()


def test_resuming_a_completed_run_publishes_nothing_further(
    fixture_repo: Path, bare_remote: Path, tmp_path: Path,
):
    base = git.head_sha(fixture_repo)
    spec = spec_for(base, publication_policy={"mode": "feature_branch",
                                              "branch_prefix": "pw-dev",
                                              "allow_existing_branch": None})
    bin_dir = tmp_path / "bin"
    config = make_run_config(
        fixture_repo, tmp_path, fake_codex(bin_dir, {
            "planner": spec, "reviewer": approval(spec, "PLACEHOLDER", "PLACEHOLDER")}),
        fake_claude(bin_dir, edits=PASSING_EDIT), mode="feature_branch",
    )
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="feature_branch", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        assert controller.execute(imported_spec=spec) is RunState.COMPLETE
    finally:
        controller.release()

    receipt = json.loads(
        (config.runs_dir() / run_id / "publication-receipt.json").read_text(encoding="utf-8")
    )
    again = Controller(config, store=store, run_id=run_id, brain="automatic",
                       reporter=lambda line: None)
    again.acquire()
    try:
        state = again.resume()
    finally:
        again.release()
    assert state is RunState.COMPLETE

    count = subprocess.run(  # noqa: S603
        ["git", "rev-list", "--count", f"refs/heads/{receipt['branch']}", f"^{base}"],
        cwd=bare_remote, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert count == "1", "resuming a published run must not publish again"
    store.close()


def test_a_resumed_run_uses_the_configuration_it_started_with(fixture_repo: Path, tmp_path: Path):
    """Editing the policy while a run is paused must not change that run's gates."""
    from pw_dev.config import Config

    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)

    frozen = Config.from_snapshot(json.loads(store.get_run(run_id)["config_json"]))
    assert frozen.publication.mode == "none"
    assert frozen.limits.max_parallel_workers == config.limits.max_parallel_workers
    assert frozen.verification_profile == config.verification_profile
    assert frozen.repo_root == config.repo_root
    assert frozen.publication.author_email == "harshkvpatil@gmail.com"
    store.close()


# =================== a killed run must not strand its exclusive resources =====
def test_reconcile_releases_resources_held_by_a_run_that_is_gone(tmp_path, fixture_repo):
    """The deadlock a killed run left behind, with no way out.

    Reconciliation resets an interrupted task to PENDING so it can be
    dispatched again -- but the resources it had acquired stayed recorded
    against it. The scheduler then refused to dispatch the very task that held
    them ("T-01: waiting on exclusive resource: alembic (held by T-01)"), and
    every task downstream waited on T-01 for ever.

    An exclusive resource is held by a running task. When reconciliation runs,
    nothing is running -- that is why it is running -- so a lock that outlived
    the process belongs to nobody.
    """
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.set_run_state(run_id, RunState.IMPLEMENT, "implementing", force=True)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "contract",
                                "exclusive_resources": ["alembic", "contracts"]}])
    store.set_task_state(run_id, "T-01", TaskState.RUNNING, "working")
    for resource in ("alembic", "contracts"):
        assert store.acquire_resource(run_id, resource, "T-01")
    assert store.held_resources(run_id) == {"alembic": "T-01", "contracts": "T-01"}

    report = reconcile(config, store, run_id)

    assert store.held_resources(run_id) == {}, (
        "a lock that outlived the process that took it belongs to nobody"
    )
    assert any("released 2 exclusive resource" in line for line in report.actions)
    store.close()


def test_reconcile_discards_a_half_applied_integration(tmp_path, fixture_repo):
    """The conflicts a second bundle hit when the first was still lying there.

    An interrupted integration leaves the bundle partly applied in the
    candidate's working tree. Nothing about that is durable -- what has been
    integrated is what has been committed -- but it was left in place, so the
    re-dispatched task's fresh bundle was applied on top of the previous one's
    debris and every file came out with conflict markers.
    """
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.set_run_state(run_id, RunState.IMPLEMENT, "implementing", force=True)

    candidate = config.runs_dir() / run_id / "candidate"
    candidate.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "."], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.name", "t"], cwd=candidate, check=True)  # noqa: S603, S607
    (candidate / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    (candidate / "kept.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "commit", "-qm", "integrated"], cwd=candidate, check=True)  # noqa: S603, S607

    # what an interrupted integration leaves behind
    (candidate / "kept.py").write_text("x = 1\n<<<<<<< ours\n", encoding="utf-8")
    (candidate / "half-applied.py").write_text("partial\n", encoding="utf-8")
    (candidate / "node_modules").mkdir()
    (candidate / "node_modules" / "dep.js").write_text("keep me\n", encoding="utf-8")

    reconcile(config, store, run_id)

    assert (candidate / "kept.py").read_text(encoding="utf-8") == "x = 1\n", (
        "the last committed integration is what the candidate returns to"
    )
    assert not (candidate / "half-applied.py").exists(), "partial work is discarded"
    assert (candidate / "node_modules" / "dep.js").exists(), (
        "ignored files are the controller's to manage, not debris to clean"
    )
    store.close()


def test_a_dry_run_reconciliation_changes_nothing(tmp_path, fixture_repo):
    """`--dry-run` said "reconcile and report only" and did neither.

    `cmd_resume` called `reconcile` unconditionally and checked `--dry-run`
    only afterwards, so the flag skipped the resume and nothing else. Every
    write reconciliation makes had already happened by the time the report was
    printed: an expired lease's task reset to PENDING, stranded exclusive
    resources released, an approval bound to a moved candidate dropped, and the
    integration checkout `reset --hard` and `clean -fd`.

    The last of those is the one that costs something. Asking what a resume
    would do discarded the uncommitted work first and then described the
    discarding in the past tense -- which was accurate, and was the bug.
    """
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    store.set_run_state(run_id, RunState.IMPLEMENT, "implementing", force=True)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "contract",
                                 "exclusive_resources": ["alembic"]}])
    store.set_task_state(run_id, "T-01", TaskState.RUNNING, "working")
    assert store.acquire_resource(run_id, "alembic", "T-01")
    store.update_run_fields(run_id, candidate_fingerprint="tree:recorded",
                            approved_fingerprint="tree:recorded")
    # an expired lease left by a process that is gone: what reconciliation
    # resets the task for
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO leases(run_id, task_id, lease_token, owner_pid, child_pid,"
            " acquired_at, heartbeat_at, expires_at_epoch) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, "T-01", "t", 999999, None, "t", "t", time.time() - 10),
        )
    assert [r["task_id"] for r in store.stale_leases(run_id)] == ["T-01"]

    candidate = config.runs_dir() / run_id / "candidate"
    candidate.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "."], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.name", "t"], cwd=candidate, check=True)  # noqa: S603, S607
    (candidate / "kept.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=candidate, check=True)  # noqa: S603, S607
    subprocess.run(["git", "commit", "-qm", "integrated"], cwd=candidate, check=True)  # noqa: S603, S607
    (candidate / "kept.py").write_text("x = 1\n<<<<<<< ours\n", encoding="utf-8")
    (candidate / "half-applied.py").write_text("partial\n", encoding="utf-8")

    report = reconcile(config, store, run_id, apply=False)

    assert (candidate / "half-applied.py").exists(), "a dry run may not discard work"
    assert (candidate / "kept.py").read_text(encoding="utf-8") == "x = 1\n<<<<<<< ours\n", (
        "a dry run may not reset the checkout it was asked about"
    )
    assert store.held_resources(run_id) == {"alembic": "T-01"}, (
        "a dry run may not release a lock the scheduler is still reasoning about"
    )
    assert store.get_task(run_id, "T-01")["state"] == TaskState.RUNNING.value, (
        "a dry run may not reset a task"
    )
    assert store.get_run(run_id)["approved_fingerprint"] == "tree:recorded", (
        "a dry run may not invalidate an approval"
    )

    rendered = report.render()
    assert report.applied is False
    assert "nothing was changed" in rendered
    assert "would:" in rendered and "action:" not in rendered, (
        "'action' is a claim about the past; nothing was done"
    )
    assert "discard them" in rendered and "discarded them" not in rendered

    # and the same reconciliation, applied, still does all of it
    applied = reconcile(config, store, run_id, apply=True)
    assert not (candidate / "half-applied.py").exists()
    assert (candidate / "kept.py").read_text(encoding="utf-8") == "x = 1\n"
    assert store.held_resources(run_id) == {}
    assert store.get_task(run_id, "T-01")["state"] == TaskState.PENDING.value
    assert store.get_run(run_id)["approved_fingerprint"] is None
    assert "action:" in applied.render() and "discarded them" in applied.render()
    store.close()


def test_a_baseline_with_an_unmeasured_skip_count_is_restored_not_recaptured(
    tmp_path, fixture_repo
):
    """Recapture is not a neutral fallback, so "unknown" must be storable.

    A check whose baseline produced nothing countable records `None`: unknown
    is not zero, and a ceiling invented from silence is unsatisfiable. The
    validator only accepted `int`, so such an artifact read as malformed and
    the run measured again -- against `candidate_dir`, which by resume time
    holds the phase's own work. The baseline exists precisely to predate that,
    so the fallback would have quietly adopted the changes as the "before".
    """
    bin_dir = tmp_path / "bin"
    config = make_run_config(fixture_repo, tmp_path, fake_codex(bin_dir, {}),
                             fake_claude(bin_dir, edits={}), mode="none")
    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic")
    controller.spec = spec_for(["repo:verify"])
    gates = controller.gate_checks()

    document = {
        "version": 2,
        "outcomes": {cid: "pass" for cid in gates},
        "skips": {cid: None for cid in gates},
    }
    store.put_json_artifact(run_id, "baseline", document)

    controller._restore_baseline()

    assert controller.baseline == document["outcomes"], (
        "an unmeasured skip count must not discard the whole baseline"
    )
    assert all(v is None for v in controller.skip_budget.values())
    store.close()
