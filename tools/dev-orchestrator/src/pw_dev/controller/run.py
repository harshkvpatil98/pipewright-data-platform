"""The run loop.

This is the deterministic part. It owns the state machine, the budgets, the
worktrees, the integration, the verification and the publication, and it calls
providers only where a judgement is genuinely needed: planning, implementing,
reviewing, repairing.

Things it refuses to do, because they are how orchestrators quietly lie:

* mark a phase complete when a budget ran out. That is `PAUSED`, and it resumes;
* count a worker's report as verification. Evidence comes from the runner;
* let an approval survive a change to the tree it approved;
* assume a timed-out provider did nothing. The worktree is re-read;
* commit anything other than the exact tree the reviewer saw.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Config
from ..errors import LimitReached, PolicyViolation, PublicationError, StateError
from ..providers.base import FATAL, RETRYABLE, FailureKind, ProviderResult
from ..providers.claude_cli import ClaudeCliAdapter
from ..providers.codex_cli import CodexCliAdapter
from ..prompts import role_prompt
from ..publish.publisher import Publisher, PublicationRefusal
from ..state.db import RunStore
from ..state.machine import RunState, TaskState, describe, is_terminal
from ..util.hashing import digest_json, tree_fingerprint
from ..util.jsonio import write_json_atomic
from ..verify.registry import registry_for
from ..verify.runner import SUCCESS_OUTCOMES, VerificationRunner
from ..workspace import git, pyenv
from ..workspace.guard import PathGuard, PathViolation, resolve_within
from ..workspace.node_modules import provide as provide_node_modules
from ..workspace.pyenv import EnvironmentReport
from ..workspace.patches import (CONTROLLER_SCRATCH, PatchBundle, apply_bundle,
                                 conflicting_paths, export_bundle, would_conflict)
from ..workspace.sandbox import (SandboxSupport, claude_config_denials,
                                 detect_sandbox_support, resolve_mode, sandbox_wrapper)
from ..workspace.sentinel import Sentinel, protected_locations
from ..workspace.worktrees import WorktreeManager
from . import roles
from .context import ContextBuilder, build_task_assignment, read_operator_context
from .discovery import discover
from .scheduler import Scheduler, TaskNode, nodes_from_spec, scope_union
from .validate_plan import validate_plan


#: Modules whose import origin proves a checkout is verifying its own code.
#: One from each layer that is installed editable: the gateway, the shared
#: library, a service, and this tool. If these four resolve inside the checkout,
#: the `.pth` composition did what it claims.
MODULE_OWNERSHIP_PROBES = ("api_gateway", "shared_python", "service_datasets", "pw_dev")


@dataclass
class Progress:
    """The concise status line. Phase, worker, check, elapsed, usage, next thing."""

    run_id: str
    state: str = RunState.DISCOVER.value
    activity: str = "starting"
    active_workers: list[str] = field(default_factory=list)
    current_check: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    usage: dict = field(default_factory=dict)
    next_dependency: str | None = None

    def line(self) -> str:
        elapsed = int(time.monotonic() - self.started_at)
        parts = [f"[{self.run_id}]", self.state, self.activity]
        if self.active_workers:
            parts.append(f"workers={','.join(self.active_workers)}")
        if self.current_check:
            parts.append(f"check={self.current_check}")
        parts.append(f"{elapsed // 60}m{elapsed % 60:02d}s")
        cost = self.usage.get("cost_usd_known")
        unknown = self.usage.get("calls_without_cost", 0)
        if cost is not None:
            parts.append(f"${cost:.2f}" + (f"+{unknown} unknown" if unknown else ""))
        elif self.usage.get("calls"):
            parts.append(f"cost=unknown ({self.usage['calls']} calls)")
        if self.next_dependency:
            parts.append(f"next={self.next_dependency}")
        return "  ".join(parts)


class RunAborted(Exception):
    """Raised internally to unwind to a recorded terminal or resumable state."""

    def __init__(self, state: RunState, detail: str) -> None:
        self.state = state
        self.detail = detail
        super().__init__(detail)


class Controller:
    """One run, from DISCOVER to a recorded stopping state."""

    def __init__(
        self, config: Config, *, store: RunStore, run_id: str, brain: str,
        reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.run_id = run_id
        self.brain = brain
        self.report = reporter or (lambda line: None)
        self.repo_root = config.repo_root
        self.run_dir = config.runs_dir() / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.registry = registry_for(config.verification_profile)
        self.progress = Progress(run_id=run_id)
        self._cancelled = threading.Event()
        self._lock_token: str | None = None
        self._deadline: float | None = None

        self.planner = CodexCliAdapter(config.planner)
        self.reviewer = CodexCliAdapter(config.reviewer)
        self.implementer = ClaudeCliAdapter(config.implementer)

        self.sandbox_support: SandboxSupport = detect_sandbox_support(probe=True)
        self.isolation_mode = resolve_mode(config.isolation.mode, self.sandbox_support)

        self.worktrees = WorktreeManager(self.repo_root, self.run_dir, run_id)
        self.candidate_dir = self.run_dir / "candidate"
        self.evidence_dir = self.run_dir / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        self.spec: dict | None = None
        self.spec_digest: str = ""
        self.base_commit: str = ""
        self.baseline: dict[str, str] = {}
        self.worker_reports: dict[str, dict] = {}
        self.integration_commits: dict[str, str] = {}
        self.sentinel: Sentinel | None = None
        self.notes: list[str] = []
        self.final_records: dict[str, dict] = {}
        #: task id -> the candidate fingerprint its checks passed against.
        self.checkpoints: dict[str, str] = {}

    # ------------------------------------------------------------------ setup
    def acquire(self) -> None:
        self._lock_token = self.store.acquire_run_lock(self.run_id)

    def release(self) -> None:
        if self._lock_token:
            self.store.release_run_lock(self.run_id, self._lock_token)
            self._lock_token = None

    def cancel(self) -> None:
        self._cancelled.set()

    def _check_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _check_budget(self) -> None:
        if self._cancelled.is_set():
            raise RunAborted(RunState.CANCELLED, "cancelled by the operator")
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise LimitReached(
                f"the total run budget of {self.config.limits.total_run_seconds}s is spent",
                limit="total_run_seconds",
            )

    def _emit(self, state: RunState | None = None, activity: str | None = None) -> None:
        if state is not None:
            self.progress.state = state.value
        if activity is not None:
            self.progress.activity = activity
        self.progress.usage = self.store.usage_summary(self.run_id)
        self.report(self.progress.line())

    def _transition(self, state: RunState, detail: str, **payload) -> None:
        self.store.set_run_state(self.run_id, state, detail, payload=payload or None)
        self._emit(state, detail)

    # ------------------------------------------------------------- the phases
    def execute(self, *, requested_phase: str | None = None, plan_only: bool = False,
                imported_spec: dict | None = None) -> RunState:
        # An already-set deadline is honoured rather than reset, so a caller can
        # hand this controller a budget that is already spent. A run whose wall
        # clock is gone must pause with its work preserved, and that has to be
        # reachable without configuring a zero-second budget -- which is not a
        # budget, and which plan validation now refuses as unschedulable.
        if self._deadline is None:
            self._deadline = time.monotonic() + self.config.limits.total_run_seconds
        try:
            self.discover()
            spec = imported_spec or self.plan(requested_phase)
            if spec is None:
                return RunState.WAITING_FOR_PLAN
            self.validate(spec)
            if plan_only:
                self._transition(
                    RunState.PLAN_READY,
                    "plan-only run: the specification passed structural and policy "
                    "validation. Nothing was implemented, no verification was executed and "
                    "no reviewer has seen it.",
                )
                return RunState.PLAN_READY
            self.implement()
            self.integrate_and_verify()
            verdict = self.review()
            if verdict is None:
                return RunState.WAITING_FOR_REVIEW
            return self.publish(verdict)
        except RunAborted as abort:
            self.store.set_run_state(self.run_id, abort.state, abort.detail, force=True)
            self._emit(abort.state, abort.detail)
            return abort.state
        except LimitReached as limit:
            detail = (
                f"{limit}. The run is paused with its work preserved; `pw-dev resume "
                f"{self.run_id}` continues it. This is not a completed phase."
            )
            self.store.set_run_state(self.run_id, RunState.PAUSED, detail, force=True)
            self._emit(RunState.PAUSED, detail)
            return RunState.PAUSED
        except (PolicyViolation, StateError, PublicationError) as blocked:
            self.store.set_run_state(self.run_id, RunState.BLOCKED, str(blocked)[:800], force=True)
            self._emit(RunState.BLOCKED, str(blocked)[:200])
            return RunState.BLOCKED
        finally:
            keep = self._should_keep_worktrees()
            self.worktrees.cleanup(keep=keep)
            if not keep:
                self.worktrees.prune_branches()

    def _should_keep_worktrees(self) -> bool:
        state = RunState(self.store.get_run(self.run_id)["state"])
        return state in (RunState.PAUSED, RunState.BLOCKED, RunState.NEEDS_FIX,
                         RunState.WAITING_FOR_PLAN, RunState.WAITING_FOR_REVIEW)

    def check_parameters(self) -> dict[str, str]:
        """Controller-supplied bindings for parameterised checks.

        `scenario` names the live acceptance document a phase must provide, and
        it is derived from the specification's own phase id rather than chosen
        by a worker: a task that could name the scenario could point the
        required check at an easier one.
        """
        if not self.spec:
            return {}
        slug = re.sub(r"[^a-z0-9-]+", "-", str(self.spec["phase_id"]).lower()).strip("-")
        return {"scenario": slug or "phase"}

    def _verification_runner(self) -> VerificationRunner:
        return VerificationRunner(
            self.registry, store=self.store, run_id=self.run_id,
            base_commit=self.base_commit, spec_digest=self.spec_digest,
            artifacts_dir=self.evidence_dir, parameters=self.check_parameters(),
            isolation_mode=self.isolation_mode, run_dir=self.run_dir,
            repo_root=self.config.repo_root,
        )

    def gate_checks(self) -> list[str]:
        """Everything the integrated candidate must pass.

        The specification's required checks *plus* the profile's gates. A plan
        cannot drop a gate by omitting it; the controller adds it back.
        """
        assert self.spec is not None
        return list(dict.fromkeys([
            *self.spec["required_verifications"],
            *(check.id for check in self.registry.gates()),
        ]))

    def outstanding_gate_failures(self) -> list[str]:
        """Gate checks that are not passing on the final candidate.

        A pre-existing failure stays visible. It stops blocking only when the
        specification names it in `accepted_preexisting_failures` -- which is a
        stated, reviewable decision rather than a silent absorption. A check this
        run broke is never covered by that list, because it was passing at
        baseline.
        """
        assert self.spec is not None
        scoped = {
            entry["verification_id"]: entry["reason"]
            for entry in self.spec.get("accepted_preexisting_failures", [])
        }
        outstanding: list[str] = []
        for check_id in self.gate_checks():
            record = self.final_records.get(check_id)
            outcome = (record or {}).get("outcome")
            if outcome in SUCCESS_OUTCOMES:
                continue
            was_failing = self.baseline.get(check_id) not in SUCCESS_OUTCOMES
            if was_failing and check_id in scoped and self._waivable(check_id):
                self.notes.append(
                    f"{check_id} was already {self.baseline.get(check_id)} before this run and "
                    f"the specification scopes it out: {scoped[check_id]}"
                )
                continue
            outstanding.append(
                f"{check_id}: {outcome or 'never executed'}"
                + (" (already failing at baseline; the specification does not scope it)"
                   if was_failing else " (regressed during this run)")
            )
        return outstanding

    def _waivable(self, check_id: str) -> bool:
        """Whether `accepted_preexisting_failures` may scope this check out.

        A required live acceptance path may not be. Its scenario does not exist
        until the phase writes it, so the check is *always* non-passing at
        baseline -- which means the general "this was already failing" mechanism
        would waive the one gate whose whole purpose is that a missing scenario
        cannot pass. Refused here as well as at plan validation, because a
        specification can arrive by import.
        """
        if check_id not in self.registry:
            return True
        if self.registry.get(check_id).evidence_class != "required_live":
            return True
        self.notes.append(
            f"{check_id} is a required live acceptance path and was not waived: a "
            f"scenario that does not exist yet is non-passing at baseline, so scoping it "
            f"out would waive the gate rather than record a pre-existing failure."
        )
        return False

    # --------------------------------------------------------------- DISCOVER
    def discover(self) -> dict:
        self._emit(RunState.DISCOVER, "reading the repository")
        findings = discover(self.repo_root)
        self.base_commit = findings.head_sha
        self.store.update_run_fields(self.run_id, base_commit=self.base_commit)
        digest = self.store.put_json_artifact(self.run_id, "discovery", findings.to_dict())

        if findings.dirty_paths or findings.untracked_paths:
            note = (
                f"the working tree has {len(findings.dirty_paths)} modified and "
                f"{len(findings.untracked_paths)} untracked file(s). They were recorded and "
                f"left alone; this run works from the clean committed base "
                f"{self.base_commit[:12]}."
            )
            self.notes.append(note)
            self.store.event(self.run_id, "discovery.uncommitted", note, payload={
                "modified": findings.dirty_paths[:50],
                "untracked": findings.untracked_paths[:50],
            })

        for contradiction in findings.contradictions:
            self.store.event(self.run_id, "discovery.contradiction", contradiction)

        self.store.event(
            self.run_id, "discovery.complete",
            f"base {self.base_commit[:12]}, "
            f"{len(findings.eligible_phases())} eligible phase(s), "
            f"{len(findings.contradictions)} contradiction(s)",
            payload={"artifact": digest, "recommended_phase": findings.recommended_phase},
        )
        self._discovery = findings
        return findings.to_dict()

    # ------------------------------------------------------------------- PLAN
    def plan(self, requested_phase: str | None) -> dict | None:
        self._transition(RunState.PLAN, "the planner is producing a specification")
        operator = self._operator_context()
        if self.brain == "interactive":
            self._export_plan_request(requested_phase, operator)
            self.store.set_run_state(
                self.run_id, RunState.WAITING_FOR_PLAN,
                f"exported a planning packet; supply a specification with "
                f"`pw-dev plan-import {self.run_id} <spec.json>`",
            )
            self._emit(RunState.WAITING_FOR_PLAN, "waiting for an operator-supplied specification")
            return None

        builder = ContextBuilder(self.repo_root, self.config.limits)
        context_text, problems = roles.gather_context(
            builder, roles.default_planner_context(self.repo_root),
            "canonical repository documents and the verification scripts",
        )
        for problem in problems:
            self.store.event(self.run_id, "context.problem", problem)

        prompt = roles.plan_prompt(
            discovery=self._discovery.to_dict(),
            registry_ids=self.registry.describe(),
            base_commit=self.base_commit,
            config_summary={
                "limits": {
                    "max_parallel_workers": self.config.limits.max_parallel_workers,
                    "per_task_seconds": self.config.limits.per_task_seconds,
                    "total_run_seconds": self.config.limits.total_run_seconds,
                    "repair_rounds_per_task": self.config.limits.repair_rounds_per_task,
                },
                "publication_policy": {
                    "mode": self.config.publication.mode,
                    "branch_prefix": self.config.publication.branch_prefix,
                    "allow_existing_branch": self.config.publication.allow_existing_branch,
                },
            },
            requested_phase=requested_phase,
            context_text=context_text,
            operator_context=operator.render(),
        )

        result = self._call_provider(
            self.planner, role="planner", prompt=prompt, cwd=self.repo_root,
            timeout=self.config.limits.plan_seconds, schema_id="phase_spec/v1",
            system_prompt=role_prompt("planner"),
        )
        spec = result.data
        assert isinstance(spec, dict)
        return spec

    def _operator_context(self):
        """Read and record `--context-file` inputs before the planner is called.

        The digests go into the event log and into the planning packet, so a
        specification can be traced back to the exact text that shaped it. A
        file that could not be read is an event, never a silent omission.
        """
        paths = list(self.config.planner_context_files)
        operator = read_operator_context(self.repo_root, paths, self.config.limits)
        for problem in operator.problems:
            self.store.event(self.run_id, "context.problem",
                             f"operator context: {problem}")
        if operator.digests:
            self.store.event(
                self.run_id, "context.operator",
                "planning context supplied by the operator: "
                + ", ".join(
                    f"{d['path']} (file sha256 {(d['source_digest'] or 'unreadable')[:16]}, "
                    f"{d['source_bytes']} bytes"
                    + (f"; TRUNCATED to {d['delivered_characters']} characters in the "
                       f"packet, delivered sha256 {d['delivered_digest'][:16]})"
                       if d["truncated"] else ")")
                    for d in operator.digests),
                payload={"files": operator.digests},
            )
        elif paths:
            raise PolicyViolation(
                "every --context-file was rejected, so the planner would have been called "
                "without the corrections it was told to apply: "
                + "; ".join(operator.problems)
            )
        return operator

    def _export_plan_request(self, requested_phase: str | None, operator=None) -> None:
        """Interactive brain: write everything the application needs to plan."""
        packet = {
            "schema_version": "plan_request/v1",
            "run_id": self.run_id,
            "base_commit": self.base_commit,
            "requested_phase": requested_phase,
            "discovery": self._discovery.to_dict(),
            "verification_registry": [
                {"id": cid, "description": d} for cid, d in self.registry.describe()
            ],
            "adopted_policy": {
                "publication": {
                    "mode": self.config.publication.mode,
                    "branch_prefix": self.config.publication.branch_prefix,
                },
                "limits": {
                    "max_parallel_workers": self.config.limits.max_parallel_workers,
                    "total_run_seconds": self.config.limits.total_run_seconds,
                    "repair_rounds_per_task": self.config.limits.repair_rounds_per_task,
                },
            },
            "schema": "phase_spec/v1",
            "planner_prompt": role_prompt("planner"),
            "operator_context": {
                "files": operator.digests if operator else [],
                "text": operator.render() if operator else "",
            },
        }
        path = self.run_dir / "plan-request.json"
        write_json_atomic(path, packet)
        self.store.put_json_artifact(self.run_id, "plan_request", packet)
        self.report(f"plan request written to {path}")

    # ---------------------------------------------------------- VALIDATE_PLAN
    def validate(self, spec: dict) -> None:
        self._transition(RunState.VALIDATE_PLAN, "validating the specification")
        report = validate_plan(
            spec, config=self.config, registry=self.registry,
            base_commit=self.base_commit, repo_root=self.repo_root,
        )
        for warning in report.warnings:
            self.store.event(self.run_id, "plan.warning", warning)
        if not report.ok:
            for error in report.errors:
                self.store.event(self.run_id, "plan.error", error)
            raise PolicyViolation(
                "the specification did not pass validation:\n" + report.render()
            )

        self.spec = spec
        self.spec_digest = digest_json(spec)
        digest = self.store.put_json_artifact(self.run_id, "phase_spec", spec)
        write_json_atomic(self.run_dir / "phase-spec.json", spec)
        self.store.update_run_fields(
            self.run_id, phase_id=spec["phase_id"], spec_digest=self.spec_digest,
        )
        self.store.create_tasks(self.run_id, spec["tasks"])
        self.store.event(
            self.run_id, "plan.accepted",
            f"phase {spec['phase_id']}: {len(spec['requirements'])} requirements, "
            f"{len(spec['tasks'])} tasks, {len(report.warnings)} warning(s)",
            payload={"artifact": digest, "spec_digest": self.spec_digest},
        )

    # -------------------------------------------------------------- IMPLEMENT
    def implement(self, *, resuming: bool = False) -> None:
        assert self.spec is not None
        self._transition(RunState.IMPLEMENT, "dispatching workers")

        self._prepare_candidate(reuse=resuming)
        if resuming and self.baseline:
            self.store.event(
                self.run_id, "baseline.reused",
                f"reusing the baseline captured before this run began "
                f"({len(self.baseline)} checks)",
            )
        else:
            self._capture_baseline()

        nodes = nodes_from_spec(self.spec)
        scheduler = Scheduler(
            nodes, max_parallel=min(
                self.spec["resource_limits"]["max_parallel_workers"],
                self.config.limits.max_parallel_workers,
            ),
        )
        # A resumed run does not re-dispatch work that is already integrated --
        # except a checkpoint, whose pass described the candidate as it was at
        # the time. `_checkpoint_is_current` asks the durable evidence whether
        # that is still the tree, so a resumed run inherits a verdict only when
        # it still applies.
        done: set[str] = set()
        if resuming:
            fingerprint = tree_fingerprint(self.candidate_dir)
            for row in self.store.get_tasks(self.run_id):
                if row["state"] not in (TaskState.INTEGRATED.value, TaskState.DONE.value):
                    continue
                node = next((n for n in nodes if n.id == row["task_id"]), None)
                if node is not None and node.is_checkpoint():
                    if not self._checkpoint_is_current(node, fingerprint):
                        self.store.event(
                            self.run_id, "checkpoint.stale",
                            f"{node.id} passed against an earlier candidate; it is "
                            f"re-checked against {fingerprint[:20]} rather than inherited",
                            task_id=node.id,
                        )
                        continue
                    self.checkpoints[node.id] = fingerprint
                done.add(row["task_id"])
        if done:
            self.store.event(
                self.run_id, "implement.resumed",
                f"{len(done)} task(s) were already integrated and are not re-run: "
                f"{sorted(done)}",
            )
        running: dict[str, concurrent.futures.Future] = {}

        # Watch the protected *files* for the whole run. Worker checkouts are not
        # watched as trees here, because they legitimately change while their own
        # worker runs; cross-worktree writes are caught by the per-task guard and
        # by the enforced boundary.
        watched_files, _ = protected_locations(
            self.repo_root, self.config.state_dir, self.run_dir, self.worktrees.root,
        )
        self.sentinel = Sentinel.capture(files=watched_files, trees=[])

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=scheduler.max_parallel, thread_name_prefix="pw-worker",
        ) as pool:
            while len(done) < len(nodes):
                self._check_budget()
                finished = [tid for tid, future in running.items() if future.done()]
                for task_id in finished:
                    future = running.pop(task_id)
                    self._collect(task_id, future, done, scheduler)
                if len(done) >= len(nodes):
                    # The last task finished during this iteration. Falling
                    # through would reach the "nothing can proceed" check with
                    # nothing left to do and report a deadlock that is really
                    # a completed graph.
                    break

                ready = scheduler.ready(
                    done=done, running=set(running),
                    held_resources=self.store.held_resources(self.run_id),
                )
                for node in ready:
                    for resource in node.effective_resources():
                        self.store.acquire_resource(self.run_id, resource, node.id)
                    if node.is_controller_executed():
                        # Nothing to write, so nobody to dispatch. Running the
                        # checks is the whole task, and the controller owns that.
                        self.store.set_task_state(
                            self.run_id, node.id, TaskState.RUNNING,
                            "controller-executed checkpoint; no worker is dispatched",
                        )
                        try:
                            self._run_checkpoint(node)
                        finally:
                            for resource in node.effective_resources():
                                self.store.release_resource(self.run_id, resource, node.id)
                        done.add(node.id)
                        continue
                    running[node.id] = pool.submit(self._run_task, node)
                    self.store.set_task_state(
                        self.run_id, node.id, TaskState.DISPATCHED,
                        f"dispatched to a {self.implementer.name} worker",
                    )

                self.progress.active_workers = sorted(running)
                pending = [n for n in nodes if n.id not in done and n.id not in running]
                self.progress.next_dependency = (
                    scheduler.blocked_reason(
                        pending[0], done=done, running=set(running),
                        held_resources=self.store.held_resources(self.run_id),
                    ) if pending else None
                )
                self._emit(activity=f"{len(done)}/{len(nodes)} tasks integrated")

                if not running and not ready:
                    stuck = [n.id for n in nodes if n.id not in done]
                    raise PolicyViolation(
                        f"no task can proceed and {len(stuck)} remain: {stuck}. "
                        f"Reasons: " + "; ".join(
                            f"{n}: {scheduler.blocked_reason(scheduler.nodes[n], done=done, running=set(), held_resources=self.store.held_resources(self.run_id))}"
                            for n in stuck[:5]
                        )
                    )
                if running:
                    concurrent.futures.wait(
                        list(running.values()), timeout=5,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )

        self.progress.active_workers = []
        tampering = self.sentinel.diff() if self.sentinel else []
        if tampering:
            raise PolicyViolation(
                "protected locations changed during the run: " + "; ".join(tampering)
            )

    def _assert_scope_resolves_inside(self, node: TaskNode, checkout: Path) -> None:
        """Every root a task is anchored at must resolve inside its own checkout.

        The sandbox grants the worktree; this checks, before the worker starts,
        that what the specification anchored the task at is actually reachable
        there -- and that nothing resolves out of it through a symlink. Same
        literal-versus-pattern rule as the guard, so a dynamic-route directory
        is an anchor and not a wildcard.
        """
        for root in node.guard().literal_roots():
            resolved = resolve_within(checkout, root)
            self.store.event(
                self.run_id, "scope.anchor",
                f"{root} resolves inside {checkout.name}", task_id=node.id,
                payload={"root": root, "resolved": str(resolved)},
            )

    def _collect(self, task_id: str, future: concurrent.futures.Future,
                 done: set[str], scheduler: Scheduler) -> None:
        node = scheduler.nodes[task_id]
        try:
            bundle = future.result()
        except (PolicyViolation, PathViolation) as violation:
            self.store.set_task_state(self.run_id, task_id, TaskState.BLOCKED, str(violation)[:500])
            raise
        except LimitReached:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised as a run failure
            self.store.set_task_state(self.run_id, task_id, TaskState.FAILED, str(exc)[:500])
            raise
        finally:
            for resource in node.effective_resources():
                self.store.release_resource(self.run_id, resource, task_id)

        self._integrate_task(task_id, bundle)
        if node.is_checkpoint():
            self._run_checkpoint(node)
        done.add(task_id)

    def _run_checkpoint(self, node: TaskNode) -> None:
        """Run a checkpoint's declared checks against the candidate, and gate on them.

        Three things make this different from the advisory checks a worker asks
        for while it iterates:

        * **the controller chooses what runs.** The checks come from the task's
          declared `verification_ids` in the accepted specification, not from
          the worker's `verification_requests`. A worker that omits them, or
          asks for something easier, changes nothing;
        * **it runs against the integrated candidate**, not the worker's
          checkout, so what is verified is the tree the phase is actually
          building;
        * **only `pass` releases the dependents.** `fail`, `skip`, `not_run`,
          `infra_unavailable`, `timeout` and `error` each say something
          different and none of them says the work is done. The specification's
          `accepted_preexisting_failures` does not apply here either: that
          mechanism exists for a check the phase inherited already broken, and
          a checkpoint is a statement about this phase's own work.

        The passing fingerprint is recorded. A later task that changes the
        candidate invalidates it, and `_stale_checkpoints` refuses to let a
        resumed run inherit a pass that described a different tree.
        """
        assert self.spec is not None
        required = list(dict.fromkeys(node.verification_ids))
        if not required:
            self.store.event(
                self.run_id, "checkpoint.empty",
                f"{node.id} is a checkpoint that names no verification_ids; it gates "
                f"nothing", task_id=node.id,
            )
            return

        fingerprint = tree_fingerprint(self.candidate_dir)
        self._emit(activity=f"checkpoint {node.id}: {len(required)} required check(s)")
        runner = self._verification_runner()
        records = runner.run_many(
            required, checkout=self.candidate_dir, candidate_fingerprint=fingerprint,
            task_id=node.id, cancel_check=self._check_cancelled,
            on_start=lambda cid: setattr(self.progress, "current_check", f"{node.id}:{cid}"),
        )
        self.progress.current_check = None

        outcomes = {r["verification_id"]: r["outcome"] for r in records}
        missing = [check_id for check_id in required if check_id not in outcomes]
        failing = [
            f"{check_id}: {outcomes[check_id]}"
            for check_id in required
            if check_id in outcomes and outcomes[check_id] not in SUCCESS_OUTCOMES
        ]
        if missing or failing:
            detail = "; ".join(failing + [f"{c}: never executed" for c in missing])
            self.store.set_task_state(
                self.run_id, node.id, TaskState.NEEDS_FIX,
                f"checkpoint not met: {detail}"[:500],
            )
            raise PolicyViolation(
                f"{node.id} is a verification checkpoint and it did not pass against "
                f"candidate {fingerprint[:20]}: {detail}. Its dependents "
                f"({', '.join(self._dependents_of(node.id)) or 'none'}) are not released, "
                f"because only a passing check says the work behind them is done."
            )

        self.checkpoints[node.id] = fingerprint
        self.store.set_task_state(
            self.run_id, node.id, TaskState.INTEGRATED,
            f"checkpoint met against candidate {fingerprint[:20]}: "
            f"{', '.join(required)}",
        )
        self.store.event(
            self.run_id, "checkpoint.passed",
            f"{node.id}: {', '.join(required)} passed against candidate "
            f"{fingerprint[:20]}",
            task_id=node.id, payload={"checks": required, "candidate": fingerprint},
        )

    def _checkpoint_is_current(self, node: TaskNode, fingerprint: str) -> bool:
        """Whether this checkpoint's evidence describes the candidate as it is now.

        Read from the recorded evidence rather than from memory, because a
        resumed run is a new process and the only durable statement about what
        was verified is the evidence itself -- which carries the fingerprint of
        the tree each check actually ran against.
        """
        required = set(node.verification_ids)
        if not required:
            return True
        passing = {
            record["verification_id"]
            for record in self.store.evidence_for(
                self.run_id, candidate_fingerprint=fingerprint)
            if record.get("task_id") == node.id
            and record["outcome"] in SUCCESS_OUTCOMES
        }
        return required.issubset(passing)

    def _dependents_of(self, task_id: str) -> list[str]:
        assert self.spec is not None
        return sorted(t["id"] for t in self.spec["tasks"] if task_id in t["depends_on"])

    def _stale_checkpoints(self) -> list[str]:
        """Checkpoints whose passing evidence describes an earlier candidate.

        A checkpoint passes against a specific tree. Anything integrated
        afterwards produces a different tree, and the pass no longer describes
        what is about to be committed. Reported so a resumed run rechecks rather
        than inherits.
        """
        if not self.checkpoints:
            return []
        current = tree_fingerprint(self.candidate_dir)
        return sorted(task_id for task_id, seen in self.checkpoints.items()
                      if seen != current)

    # ------------------------------------------------------------- one worker
    def _run_task(self, node: TaskNode) -> PatchBundle:
        assert self.spec is not None
        task_spec = next(t for t in self.spec["tasks"] if t["id"] == node.id)
        attempt = 1
        lease = self.store.acquire_lease(
            self.run_id, node.id, ttl_seconds=self.config.limits.per_task_seconds + 300,
        )
        try:
            base = self.integration_commits.get("__latest__", self.base_commit)
            worktree = self.worktrees.create(node.id, base_commit=base, attempt=attempt)
            self.worktrees.verify_distinct(worktree)
            self.store.set_task_state(
                self.run_id, node.id, TaskState.RUNNING,
                f"working in {worktree.path.name} from {base[:12]}",
                worktree=str(worktree.path),
            )

            self._assert_scope_resolves_inside(node, worktree.path)
            # Before the provider call, not after: a checkout that cannot verify
            # its own code is knowable in a tenth of a second, and finding out
            # afterwards costs an implementation call to learn it.
            self._require_environment(worktree.path, what=f"{node.id}'s checkout")

            assignment = build_task_assignment(
                run_id=self.run_id, task=task_spec, spec=self.spec,
                base_commit=self.base_commit,
                prerequisite_fingerprint=worktree.fingerprint(),
                spec_digest=self.spec_digest, limits=self.config.limits,
                prerequisite_artifacts=[
                    {"task_id": dep, "kind": "worker_report",
                     "digest": self.worker_reports[dep].get("__digest__", "")}
                    for dep in node.depends_on if dep in self.worker_reports
                ],
            )
            self.store.put_json_artifact(
                self.run_id, "task_assignment", assignment, task_id=node.id,
            )

            builder = ContextBuilder(worktree.path, self.config.limits)
            context_text, problems = roles.gather_context(
                builder, task_spec.get("context_paths", []),
                "named by the specification as task-relevant",
            )
            for problem in problems:
                self.store.event(self.run_id, "context.problem", problem, task_id=node.id)

            prompt = roles.worker_prompt(assignment=assignment, context_text=context_text)
            prompt_role = "verifier" if node.role == "verification" else "worker"

            result = self._call_provider(
                self.implementer, role=f"worker:{node.id}", prompt=prompt,
                cwd=worktree.path, timeout=self.config.limits.per_task_seconds,
                schema_id="worker_report/v1", writable=True,
                system_prompt=role_prompt(prompt_role), task_id=node.id,
                sandbox_roots=[worktree.path],
            )
            report = result.data
            assert isinstance(report, dict)

            if report["status"] == "blocked":
                raise PolicyViolation(
                    f"{node.id} reported blocked: {'; '.join(report['blockers']) or report['summary']}"
                )

            bundle = export_bundle(worktree.path, node.id, base)
            guard = node.guard()
            _, violations = guard.partition(bundle.changed_paths)
            if violations:
                raise PathViolation(
                    violations[0].path,
                    f"{node.id} wrote {len(violations)} path(s) outside its declared ownership: "
                    + "; ".join(f"{v.path} ({v.reason})" for v in violations[:5]),
                )

            undeclared = sorted(set(bundle.changed_paths) - set(report["changed_paths"]))
            if undeclared:
                self.store.event(
                    self.run_id, "worker.undeclared_changes",
                    f"{node.id} changed {len(undeclared)} path(s) it did not report: "
                    f"{undeclared[:8]}",
                    task_id=node.id,
                )

            self._record_claims(node.id, report, worktree.path, bundle)

            digest = self.store.put_json_artifact(
                self.run_id, "worker_report", report, task_id=node.id,
            )
            report["__digest__"] = digest
            self.worker_reports[node.id] = report
            patch_digest = self.store.put_artifact(
                self.run_id, "patch", bundle.diff.encode("utf-8"),
                task_id=node.id, suffix=".patch",
            )
            self.store.set_task_state(
                self.run_id, node.id, TaskState.REPORTED,
                f"reported {report['status']} with {len(bundle.changed_paths)} changed path(s)",
                report_digest=digest, patch_digest=patch_digest,
            )
            return bundle
        finally:
            self.store.release_lease(self.run_id, node.id, lease)

    def _record_claims(self, task_id: str, report: dict, worktree: Path,
                       bundle: PatchBundle) -> None:
        """Run the checks the worker asked for, and compare them against its claims.

        A worker saying a test passed is a claim. If the runner disagrees, or if
        nothing was run at all, that is recorded here and handed to the reviewer
        rather than quietly accepted.
        """
        # Rebuilt from scratch, not reused, and its module origins re-proved.
        # A worker has had write access to this checkout, and where the host
        # cannot enforce the carve-out above there is nothing but this standing
        # between a rewritten interpreter and the controller running it.
        self._require_environment(
            worktree, what=f"{task_id}'s checkout after the worker ran", rebuild=True,
        )
        requested = [
            check_id for check_id in report.get("verification_requests", [])
            if check_id in self.registry
        ]
        rejected = [
            check_id for check_id in report.get("verification_requests", [])
            if check_id not in self.registry
        ]
        for check_id in rejected:
            self.store.event(
                self.run_id, "verification.rejected",
                f"{task_id} requested {check_id!r}, which is not a registered verification",
                task_id=task_id,
            )

        runner = self._verification_runner()
        fingerprint = tree_fingerprint(worktree)
        records = runner.run_many(
            requested, checkout=worktree, candidate_fingerprint=fingerprint,
            task_id=task_id, cancel_check=self._check_cancelled,
            on_start=lambda cid: setattr(self.progress, "current_check", f"{task_id}:{cid}"),
        )
        self.progress.current_check = None

        observed = {r["verification_id"]: r["outcome"] for r in records}
        for claim in report.get("tests_claimed", []):
            if claim["claimed_outcome"] != "pass":
                continue
            matching = [
                outcome for check_id, outcome in observed.items()
                if claim["name"] in check_id or check_id in claim["name"]
            ]
            if not matching:
                self.store.event(
                    self.run_id, "worker.unverified_claim",
                    f"{task_id} claims {claim['name']!r} passed, but no runner evidence "
                    f"covers it. Recorded as an unverified claim.",
                    task_id=task_id, payload={"claim": claim["name"]},
                )
            elif not any(outcome in SUCCESS_OUTCOMES for outcome in matching):
                self.store.event(
                    self.run_id, "worker.contradicted_claim",
                    f"{task_id} claims {claim['name']!r} passed; the runner recorded "
                    f"{matching}.",
                    task_id=task_id, payload={"claim": claim["name"], "observed": matching},
                )
        del bundle

    # -------------------------------------------------------------- INTEGRATE
    def _prepare_candidate(self, *, reuse: bool = False) -> None:
        """One controller-owned integration checkout at the run's base.

        `reuse` keeps an existing checkout, which is what a resumed run does:
        throwing it away would discard every integrated task and re-run work
        that already succeeded.
        """
        if reuse and self.candidate_dir.is_dir() and (self.candidate_dir / ".git").exists():
            self.integration_commits["__latest__"] = git.head_sha(self.candidate_dir)
            self._require_environment(self.candidate_dir, what="the resumed candidate")
            return
        if self.candidate_dir.exists():
            self.worktrees.destroy(self.candidate_dir)
        branch = f"pw-dev/{self.run_id}/candidate"
        git.git(self.repo_root, ["branch", "-D", branch], check=False)
        git.add_worktree(self.repo_root, self.candidate_dir, self.base_commit, branch)
        self.integration_commits["__latest__"] = self.base_commit
        self._require_environment(self.candidate_dir, what="the integration candidate")

    def _link_environment(self, checkout: Path, *, rebuild: bool = False) -> EnvironmentReport:
        """Give a checkout everything its checks need to run against *its own* code.

        `node_modules` is shared from the original checkout: JavaScript
        dependencies are not editable installs of this repository's source, so
        borrowing them cannot make a check describe the wrong tree.

        Python is not shareable that way and is not shared. `workspace.pyenv`
        builds this checkout its own interpreter whose `sys.path` puts *this*
        checkout's first-party source ahead of a shared third-party
        installation. Symlinking the original `.venv` would have been shorter
        and would have made every Python check verify the original checkout,
        which is worse than a check that says it did not run.

        The result is returned rather than swallowed: a checkout without a
        usable environment is a condition the caller has to act on, not a line
        in a log.
        """
        if not self.python_environment_needed():
            report = EnvironmentReport(
                checkout=Path(checkout), prepared=True,
                problems=(),
            )
            self.store.event(
                self.run_id, "environment.not_required",
                f"no check in the {self.config.verification_profile!r} profile declares a "
                f"Python environment, so {Path(checkout).name} is not given one",
            )
        else:
            report = pyenv.prepare(
                checkout, shared_venv=self.repo_root / ".venv",
                timeout_seconds=self.config.limits.environment_seconds,
                reuse=not rebuild,
            )
            self.store.event(
                self.run_id,
                "environment.prepared" if report.prepared else "environment.failed",
                report.describe(), payload=report.to_dict(),
            )
        if report.missing_requirements:
            self.notes.append(
                f"{checkout.name} declares {len(report.missing_requirements)} requirement(s) "
                f"the shared installation cannot provide "
                f"({', '.join(report.missing_requirements[:6])}). Checks that import them "
                f"will fail here, visibly; adding a dependency needs the repository's own "
                f"environment rebuilt."
            )
        try:
            provided = provide_node_modules(self.repo_root, checkout)
        except (OSError, shutil.Error) as exc:
            self.store.event(
                self.run_id, "environment.link_failed",
                f"could not provide node_modules to {checkout.name}: {exc}",
            )
        else:
            if provided:
                self.store.event(
                    self.run_id, "environment.node_modules",
                    f"{checkout.name} was given its own copy of {len(provided)} "
                    f"dependency tree(s): {', '.join(provided)}",
                )
        return report

    def python_environment_needed(self) -> bool:
        """Whether any registered check would use a Python environment at all.

        The fixture profile's checks run `python3 -m unittest` against a
        three-file repository and declare no prerequisites. Building a
        virtualenv for a checkout whose checks never look at one is work with no
        reader, and refusing to proceed without it would be a prerequisite this
        profile does not have.
        """
        return any("venv" in check.requires for check in self.registry.all())

    def _require_environment(self, checkout: Path, *, what: str,
                             rebuild: bool = False) -> None:
        """Prepare a checkout's environment, and refuse to continue without one.

        Called before the provider is, so a checkout that cannot be verified
        does not first consume an implementation call. The alternative -- run
        the worker, then discover at integration that nothing here could have
        been checked -- spends budget to learn something knowable in a tenth of
        a second.
        """
        report = self._link_environment(checkout, rebuild=rebuild)
        if not self.python_environment_needed():
            return
        if not report.usable:
            raise PolicyViolation(
                f"{what} has no usable Python environment, so nothing verified here would "
                f"mean anything: " + "; ".join(report.problems)
            )
        problems = pyenv.assert_module_origins(checkout, MODULE_OWNERSHIP_PROBES)
        if problems:
            raise PolicyViolation(
                f"{what} does not import its own code:\n  " + "\n  ".join(problems)
                + "\nEvery Python check here would describe a different tree."
            )
        self.store.event(
            self.run_id, "environment.verified",
            f"{checkout.name} imports {len(MODULE_OWNERSHIP_PROBES)} probe module(s) from "
            f"its own tree",
            payload={"modules": list(MODULE_OWNERSHIP_PROBES)},
        )

    def _integrate_task(self, task_id: str, bundle: PatchBundle) -> None:
        assert self.spec is not None
        task_spec = next(t for t in self.spec["tasks"] if t["id"] == task_id)
        guard = PathGuard(task_spec["allowed_paths"], task_spec["forbidden_paths"])

        if would_conflict(self.candidate_dir, bundle):
            self.store.event(
                self.run_id, "integrate.conflict",
                f"{task_id} conflicts with the candidate; routing to a bounded integration task",
                task_id=task_id,
            )
            self._resolve_conflict(task_id, bundle)
            return

        applied = apply_bundle(self.candidate_dir, bundle, guard=guard)
        checkpoint = self._checkpoint(task_id, applied)
        self.integration_commits[task_id] = checkpoint
        self.integration_commits["__latest__"] = checkpoint
        self.store.set_task_state(
            self.run_id, task_id, TaskState.INTEGRATED,
            f"integrated {len(applied)} path(s) at checkpoint {checkpoint[:12]}",
        )

    def _checkpoint(self, task_id: str, paths: list[str]) -> str:
        """A controller-owned checkpoint commit on the candidate branch.

        These never reach the remote: publication squashes the candidate tree
        into one commit, so nobody has to read a worker's checkpoint history.
        """
        from ..publish.identity import commit_env

        git.git(self.candidate_dir, ["add", "-A", "--", ".", *CONTROLLER_SCRATCH])
        if not git.out(self.candidate_dir, ["diff", "--cached", "--name-only"], check=False):
            return git.head_sha(self.candidate_dir)
        git.git(
            self.candidate_dir,
            ["commit", "--no-verify", "-m", f"checkpoint: integrate {task_id} ({len(paths)} paths)"],
            env_overrides=commit_env(
                self.config.publication.author_name, self.config.publication.author_email,
            ),
        )
        return git.head_sha(self.candidate_dir)

    def _resolve_conflict(self, task_id: str, bundle: PatchBundle) -> None:
        """Hand a conflict to a bounded worker rather than picking a side."""
        assert self.spec is not None
        task_spec = next(t for t in self.spec["tasks"] if t["id"] == task_id)
        try:
            apply_bundle(self.candidate_dir, bundle,
                         guard=PathGuard(task_spec["allowed_paths"], task_spec["forbidden_paths"]))
        except Exception:  # noqa: BLE001 - the conflict is the expected outcome here
            pass
        conflicts = conflicting_paths(self.candidate_dir)
        if not conflicts:
            checkpoint = self._checkpoint(task_id, bundle.changed_paths)
            self.integration_commits[task_id] = checkpoint
            self.integration_commits["__latest__"] = checkpoint
            return

        prompt = (
            "# Resolve an integration conflict\n\n"
            "Two tasks changed overlapping code. The working tree in this checkout has "
            "conflict markers in:\n\n"
            + "\n".join(f"- `{p}`" for p in conflicts)
            + "\n\nResolve each conflict so that **both** intentions survive. Do not choose a "
            "side to make the markers go away, and do not delete either change. If the two "
            "intentions genuinely cannot coexist, stop and report it as a blocker naming both.\n\n"
            f"Task being integrated: {task_id} — {task_spec['objective']}\n"
            "Write only the conflicted files listed above."
        )
        result = self._call_provider(
            self.implementer, role=f"integrate:{task_id}", prompt=prompt,
            cwd=self.candidate_dir, timeout=self.config.limits.per_task_seconds,
            schema_id="worker_report/v1", writable=True,
            system_prompt=role_prompt("worker"), task_id=task_id,
            sandbox_roots=[self.candidate_dir],
        )
        report = result.data
        if not isinstance(report, dict) or report["status"] == "blocked":
            raise PolicyViolation(
                f"the integration of {task_id} could not be resolved: "
                + "; ".join((report or {}).get("blockers", [])) or "no reason given"
            )
        remaining = conflicting_paths(self.candidate_dir)
        if remaining:
            raise PolicyViolation(
                f"conflict markers remain after integration in: {remaining}"
            )
        checkpoint = self._checkpoint(task_id, bundle.changed_paths)
        self.integration_commits[task_id] = checkpoint
        self.integration_commits["__latest__"] = checkpoint
        self.store.set_task_state(
            self.run_id, task_id, TaskState.INTEGRATED,
            f"integrated after conflict resolution at {checkpoint[:12]}",
        )

    # ----------------------------------------------------------------- VERIFY
    def _capture_baseline(self) -> None:
        """Run the required checks before any change, so a pre-existing failure stays visible."""
        assert self.spec is not None
        runner = self._verification_runner()
        fingerprint = tree_fingerprint(self.candidate_dir)
        self._emit(activity="capturing the pre-change baseline")
        self.baseline = runner.capture_baseline(
            self.gate_checks(), checkout=self.candidate_dir,
            candidate_fingerprint=fingerprint,
            on_start=lambda cid: setattr(self.progress, "current_check", f"baseline:{cid}"),
        )
        self.progress.current_check = None
        already_failing = sorted(
            cid for cid, outcome in self.baseline.items() if outcome not in SUCCESS_OUTCOMES
        )
        if already_failing:
            note = (
                f"these required checks were not passing before this run began: "
                f"{', '.join(f'{c} ({self.baseline[c]})' for c in already_failing)}. "
                f"They stay visible and prevent full completion unless the specification "
                f"explicitly resolves them."
            )
            self.notes.append(note)
            self.store.event(self.run_id, "baseline.failing", note)
        self.store.put_json_artifact(self.run_id, "baseline", self.baseline)

    def integrate_and_verify(self) -> None:
        assert self.spec is not None
        self._transition(RunState.INTEGRATE, "freezing the integrated candidate")
        git.git(self.candidate_dir, ["add", "-A", "--", ".", *CONTROLLER_SCRATCH], check=False)

        isolation_problems = self._verification_runner().check_module_isolation(
            self.candidate_dir, ("shared_python", "api_gateway"),
        )
        for problem in isolation_problems:
            self.store.event(self.run_id, "environment.isolation", problem)
        if isolation_problems and self.config.verification_profile != "fixture":
            # Verifying the wrong tree is not a lesser form of verifying. If the
            # candidate's interpreter resolves Pipewright's packages somewhere
            # else, every Python result below describes another checkout's code,
            # and recording those results as this candidate's evidence is the
            # precise false pass this run exists to prevent.
            raise PolicyViolation(
                "the candidate checkout cannot verify its own code:\n  "
                + "\n  ".join(isolation_problems)
                + "\nEvery Python check here would describe a different tree, so the "
                  "run is blocked rather than verified against the wrong source."
            )

        self.candidate_fingerprint = tree_fingerprint(self.candidate_dir)
        self.store.update_run_fields(
            self.run_id, candidate_fingerprint=self.candidate_fingerprint,
        )
        self._transition(
            RunState.VERIFY,
            f"verifying candidate {self.candidate_fingerprint[:20]}…",
        )

        runner = self._verification_runner()
        required = self.gate_checks()
        records = runner.run_many(
            required, checkout=self.candidate_dir,
            candidate_fingerprint=self.candidate_fingerprint,
            cancel_check=self._check_cancelled,
            on_start=lambda cid: setattr(self.progress, "current_check", cid),
        )
        self.progress.current_check = None

        # A check with no baseline is *unknown*, not "was passing". Defaulting
        # to pass would attribute a pre-existing failure to this run's changes
        # and burn repair rounds on something the run did not break.
        regressions = [
            r for r in records
            if r["outcome"] not in SUCCESS_OUTCOMES
            and self.baseline.get(r["verification_id"]) in SUCCESS_OUTCOMES
        ]
        self.final_records = {r["verification_id"]: r for r in records}
        if regressions:
            detail = "; ".join(
                f"{r['verification_id']} → {r['outcome']}: {r.get('detail') or ''}"[:200]
                for r in regressions
            )
            self._transition(RunState.NEEDS_FIX, f"verification regressed: {detail}")
            self._repair_from_verification(regressions)

    def _repair_from_verification(self, regressions: list[dict]) -> None:
        """Bounded repair rounds against concrete check failures."""
        assert self.spec is not None
        rounds = 0
        limit = min(
            self.spec["resource_limits"]["repair_rounds_per_task"],
            self.config.limits.repair_rounds_per_task,
        )
        previous_detail: str | None = None
        while regressions and rounds < limit:
            self._check_budget()
            rounds += 1
            detail = "; ".join(f"{r['verification_id']}:{r['outcome']}" for r in regressions)
            if detail == previous_detail and rounds > 1:
                raise LimitReached(
                    f"repair round {rounds} produced the identical failure set ({detail}); "
                    f"escalating rather than spending more rounds on no progress",
                    limit="repair_no_progress",
                )
            previous_detail = detail

            findings = [
                {
                    "id": f"V-{index:02d}", "severity": "blocker", "kind": "defect",
                    "requirement_or_rule": record["verification_id"],
                    "path": None, "location": None,
                    "failure_scenario": f"the check {record['verification_id']} reports "
                                        f"{record['outcome']}",
                    "evidence": (record.get("detail") or "")[:1500],
                    "requested_correction": "fix the cause; do not weaken the check",
                }
                for index, record in enumerate(regressions, start=1)
            ]
            self._run_repair_round(findings, label=f"verification round {rounds}")

            runner = self._verification_runner()
            self.candidate_fingerprint = tree_fingerprint(self.candidate_dir)
            records = runner.run_many(
                [r["verification_id"] for r in regressions], checkout=self.candidate_dir,
                candidate_fingerprint=self.candidate_fingerprint,
                cancel_check=self._check_cancelled,
            )
            regressions = [r for r in records if r["outcome"] not in SUCCESS_OUTCOMES]

        if regressions:
            raise LimitReached(
                f"{len(regressions)} required check(s) still failing after {rounds} repair "
                f"round(s): "
                + ", ".join(f"{r['verification_id']} ({r['outcome']})" for r in regressions),
                limit="repair_rounds_per_task",
            )
        self.store.set_run_state(
            self.run_id, RunState.VERIFY,
            f"repairs closed {rounds} round(s); required checks pass", force=True,
        )

    def _run_repair_round(self, findings: list[dict], *, label: str) -> None:
        assert self.spec is not None
        scope = scope_union(self.spec)
        assignment = build_task_assignment(
            run_id=self.run_id,
            task={
                "id": "repair", "title": f"Repair: {label}", "role": "backend",
                "objective": "Close the findings listed in this packet.",
                "depends_on": [], "requirement_ids": [r["id"] for r in self.spec["requirements"]],
                "allowed_paths": scope, "forbidden_paths": [],
                "exclusive_resources": [], "acceptance_criteria": [],
                "verification_ids": self.spec["required_verifications"],
                "context_paths": [], "notes": None,
            },
            spec=self.spec, base_commit=self.base_commit,
            prerequisite_fingerprint=tree_fingerprint(self.candidate_dir),
            spec_digest=self.spec_digest, limits=self.config.limits,
        )
        prompt = roles.worker_prompt(
            assignment=assignment, context_text="(work from the checkout you are in)",
            repair_findings=findings,
        )
        result = self._call_provider(
            self.implementer, role=f"repair:{label}", prompt=prompt,
            cwd=self.candidate_dir, timeout=self.config.limits.per_task_seconds,
            schema_id="worker_report/v1", writable=True,
            system_prompt=role_prompt("repair"), task_id=None,
            sandbox_roots=[self.candidate_dir],
        )
        report = result.data
        if isinstance(report, dict):
            self.store.put_json_artifact(self.run_id, "worker_report", report)
            changed = git.changed_paths(self.candidate_dir, self.base_commit)
            _, violations = PathGuard(scope).partition(changed)
            if violations:
                raise PathViolation(
                    violations[0].path,
                    "the repair round wrote outside the specification's scope: "
                    + "; ".join(f"{v.path} ({v.reason})" for v in violations[:5]),
                )
            self._checkpoint(f"repair-{label}", changed)
            # A repair worker had write access to the candidate, including its
            # environment. Everything verified after this point runs through
            # that interpreter, so it is rebuilt and re-proved first.
            self._require_environment(
                self.candidate_dir, what="the candidate after a repair round",
                rebuild=True,
            )

    # ----------------------------------------------------------------- REVIEW
    def review(self) -> dict | None:
        assert self.spec is not None
        self._transition(RunState.REVIEW, "independent review of the frozen candidate")
        self.candidate_fingerprint = tree_fingerprint(self.candidate_dir)
        self.store.update_run_fields(self.run_id, candidate_fingerprint=self.candidate_fingerprint)

        diff = git.out(
            self.candidate_dir, ["diff", "--no-color", self.base_commit, "--"],
            check=False, timeout=600,
        )
        if len(diff) > 400_000:
            diff = diff[:400_000] + "\n… [diff truncated; ask for specific paths]"
        evidence = self.store.evidence_for(
            self.run_id, candidate_fingerprint=self.candidate_fingerprint,
        )
        builder = ContextBuilder(self.repo_root, self.config.limits)
        baseline_text, _ = roles.gather_context(
            builder,
            sorted({p for t in self.spec["tasks"] for p in t.get("context_paths", [])})[:20],
            "baseline code as it stood before this run",
        )

        rounds = 0
        previous: list[dict] | None = None
        limit = min(
            self.spec["resource_limits"]["repair_rounds_per_task"],
            self.config.limits.repair_rounds_per_task,
        )
        while True:
            self._check_budget()
            if self.brain == "interactive":
                self._export_review(diff, evidence)
                self.store.set_run_state(
                    self.run_id, RunState.WAITING_FOR_REVIEW,
                    f"exported review evidence; import a verdict with "
                    f"`pw-dev review-import {self.run_id} <review.json>`",
                )
                self._emit(RunState.WAITING_FOR_REVIEW, "waiting for an operator-supplied review")
                return None

            prompt = roles.review_prompt(
                spec=self.spec, diff=diff, evidence=evidence,
                worker_reports=list(self.worker_reports.values()),
                candidate_fingerprint=self.candidate_fingerprint,
                base_commit=self.base_commit, spec_digest=self.spec_digest,
                baseline_context=baseline_text, run_id=self.run_id,
                previous_findings=previous,
            )
            result = self._call_provider(
                self.reviewer, role="reviewer", prompt=prompt, cwd=self.repo_root,
                timeout=self.config.limits.review_seconds, schema_id="review_findings/v1",
                system_prompt=role_prompt("reviewer"),
            )
            verdict = result.data
            assert isinstance(verdict, dict)
            self.store.put_json_artifact(self.run_id, "review", verdict)

            problems = self.check_review_binding(verdict)
            if problems:
                raise PolicyViolation(
                    "the review is not bound to this candidate: " + "; ".join(problems)
                )

            blockers = [f for f in verdict["findings"]
                        if f["severity"] in ("blocker", "major") and f["kind"] != "preference"]
            self.store.event(
                self.run_id, "review.verdict",
                f"{verdict['verdict']} with {len(verdict['findings'])} finding(s), "
                f"{len(blockers)} blocking",
            )

            if verdict["verdict"] == "APPROVE" and not blockers:
                self.store.update_run_fields(
                    self.run_id, approved_fingerprint=self.candidate_fingerprint,
                )
                return verdict
            if verdict["verdict"] == "BLOCKED":
                raise PolicyViolation(
                    "the reviewer could not complete the review: " + verdict["summary"]
                    + (f" (needs: {verdict['context_requests']})" if verdict["context_requests"] else "")
                )

            rounds += 1
            if rounds > limit:
                raise LimitReached(
                    f"review still requests changes after {limit} repair round(s): "
                    + "; ".join(f["failure_scenario"][:120] for f in blockers[:3]),
                    limit="repair_rounds_per_task",
                )
            self._transition(
                RunState.NEEDS_FIX,
                f"review round {rounds}: {len(blockers)} blocking finding(s)",
            )
            self._run_repair_round(blockers, label=f"review round {rounds}")
            self._transition(RunState.IMPLEMENT, "repairs applied; re-verifying")
            self.integrate_and_verify()
            self._transition(RunState.REVIEW, f"re-reviewing after round {rounds}")
            # The candidate changed, so the previous evidence no longer covers it.
            self.candidate_fingerprint = tree_fingerprint(self.candidate_dir)
            diff = git.out(self.candidate_dir, ["diff", "--no-color", self.base_commit, "--"],
                           check=False, timeout=600)[:400_000]
            evidence = self.store.evidence_for(
                self.run_id, candidate_fingerprint=self.candidate_fingerprint,
            )
            previous = blockers

    def check_review_binding(self, verdict: dict) -> list[str]:
        """An approval must name the tree it approved. This is where staleness dies."""
        problems: list[str] = []
        if verdict["base_commit"] != self.base_commit:
            problems.append(
                f"base commit {verdict['base_commit'][:12]} ≠ {self.base_commit[:12]}"
            )
        if verdict["candidate_fingerprint"] != self.candidate_fingerprint:
            problems.append(
                f"candidate fingerprint {verdict['candidate_fingerprint'][:20]} ≠ "
                f"{self.candidate_fingerprint[:20]}"
            )
        if verdict["spec_digest"] != self.spec_digest:
            problems.append(
                f"specification digest {verdict['spec_digest'][:12]} ≠ {self.spec_digest[:12]}"
            )
        if verdict["run_id"] != self.run_id:
            problems.append(f"run id {verdict['run_id']} ≠ {self.run_id}")
        return problems

    def _export_review(self, diff: str, evidence: list[dict]) -> None:
        packet = {
            "schema_version": "review_request/v1",
            "run_id": self.run_id,
            "base_commit": self.base_commit,
            "candidate_fingerprint": self.candidate_fingerprint,
            "spec_digest": self.spec_digest,
            "specification": self.spec,
            "diff": diff,
            "evidence": evidence,
            "worker_reports": list(self.worker_reports.values()),
            "reviewer_prompt": role_prompt("reviewer"),
            "schema": "review_findings/v1",
        }
        path = self.run_dir / "review-request.json"
        write_json_atomic(path, packet)
        self.store.put_json_artifact(self.run_id, "review_request", packet)
        self.report(f"review request written to {path}")

    # ---------------------------------------------------------------- RESUME
    def resume(self) -> RunState:
        """Reconcile, then continue from where the run actually is.

        Idempotent: a run that already published is recognised as published and
        nothing is pushed again; a run whose candidate moved has its evidence and
        approval invalidated and re-earned.
        """
        from .recovery import reconcile

        report = reconcile(self.config, self.store, self.run_id,
                           own_token=self._lock_token)
        for line in (*report.observations, *report.actions):
            self.store.event(self.run_id, "resume.reconcile", line)

        # Read the state *after* reconciling: reconciliation is what discovers
        # that a run which recorded PUSH had in fact already published, and it
        # moves the run to COMPLETE. Checking before would push a second time.
        row = self.store.get_run(self.run_id)
        state = RunState(row["state"])
        if is_terminal(state):
            self.report(f"{self.run_id} is already {state.value}; nothing to resume")
            return state
        if report.blocked_reason:
            raise StateError(report.blocked_reason)
        if not report.resumable:
            raise StateError(f"{self.run_id} cannot be resumed from {state.value}")
        if state in (RunState.WAITING_FOR_PLAN, RunState.WAITING_FOR_REVIEW):
            self.report(f"{self.run_id} is waiting for you: {describe(state)}")
            return state

        self._deadline = time.monotonic() + self.config.limits.total_run_seconds
        self.base_commit = row["base_commit"] or ""
        self.spec_digest = row["spec_digest"] or ""

        spec_path = self.run_dir / "phase-spec.json"
        if not spec_path.is_file():
            # Nothing was accepted yet, so there is nothing to continue: start over.
            self.report("no accepted specification; restarting the run from discovery")
            return self.execute()

        self.spec = json.loads(spec_path.read_text(encoding="utf-8"))
        baseline = self.store.latest_artifact(self.run_id, "baseline")
        if baseline is not None:
            self.baseline = json.loads(
                Path(baseline["path"]).read_text(encoding="utf-8")
            )
        for row_ in self.store.get_tasks(self.run_id):
            digest = row_["report_digest"]
            if digest and row_["state"] in (TaskState.INTEGRATED.value, TaskState.DONE.value):
                try:
                    self.worker_reports[row_["task_id"]] = self.store.load_json_artifact(
                        self.run_id, "worker_report", digest,
                    )
                except StateError:
                    pass

        try:
            self.store.set_run_state(
                self.run_id, RunState.IMPLEMENT,
                f"resumed from {state.value}", force=True,
            )
            self.implement(resuming=True)
            self.integrate_and_verify()
            verdict = self.review()
            if verdict is None:
                return RunState.WAITING_FOR_REVIEW
            return self.publish(verdict)
        except RunAborted as abort:
            self.store.set_run_state(self.run_id, abort.state, abort.detail, force=True)
            return abort.state
        except LimitReached as limit:
            detail = f"{limit}. The run is paused again with its work preserved."
            self.store.set_run_state(self.run_id, RunState.PAUSED, detail, force=True)
            return RunState.PAUSED
        except (PolicyViolation, StateError, PublicationError) as blocked:
            self.store.set_run_state(self.run_id, RunState.BLOCKED, str(blocked)[:800], force=True)
            return RunState.BLOCKED
        finally:
            self.worktrees.cleanup(keep=self._should_keep_worktrees())

    # ------------------------------------------------------ COMMIT / PUSH
    def publish(self, verdict: dict) -> RunState:
        assert self.spec is not None
        approved = self.store.get_run(self.run_id)["approved_fingerprint"]

        outstanding = self.outstanding_gate_failures()
        if outstanding:
            detail = (
                "required checks are not passing on the approved candidate: "
                + "; ".join(outstanding)
                + ". A run does not complete over a failing gate; list a pre-existing "
                  "failure in the specification's accepted_preexisting_failures to scope it."
            )
            self._write_receipt(
                published=False, commit_sha=None, approved=approved, push=None,
                checks=[{"name": "required checks pass", "passed": False, "detail": detail}],
                ci_status="not_triggered", new_commits=[], notes=[detail, *self.notes],
            )
            raise PolicyViolation(detail)

        if self.config.publication.mode == "none":
            self._transition(
                RunState.VERIFIED_LOCAL,
                "verified and approved locally; this run's policy did not request publication",
            )
            self._write_receipt(published=False, commit_sha=None, approved=approved,
                                push=None, checks=[], ci_status="not_triggered",
                                new_commits=[])
            return RunState.VERIFIED_LOCAL

        self._transition(RunState.COMMIT, "creating the commit for the approved tree")
        publisher = Publisher(
            repo_root=self.repo_root, policy=self.config.publication, run_id=self.run_id,
        )
        subject, body = self._compose_message()
        try:
            commit_sha, tree_sha, checks = publisher.commit(
                self.candidate_dir, base_commit=self.base_commit, subject=subject, body=body,
                approved_fingerprint=approved, allowed_paths=scope_union(self.spec),
            )
        except PublicationRefusal as refusal:
            self._write_receipt(published=False, commit_sha=None, approved=approved,
                                push=None, checks=refusal.checks, ci_status="not_triggered",
                                new_commits=[], notes=[str(refusal)])
            raise

        new_commits, problems = publisher.inspect_new_commits(
            self.candidate_dir, base_commit=self.base_commit, head=commit_sha,
        )
        if problems:
            self._write_receipt(
                published=False, commit_sha=commit_sha, approved=approved, push=None,
                checks=[*(c.to_dict() for c in checks),
                        {"name": "commit metadata", "passed": False,
                         "detail": "; ".join(problems)}],
                ci_status="not_triggered", new_commits=new_commits,
            )
            raise PublicationError(
                "refusing to publish: " + "; ".join(problems)
            )
        checks.append(type(checks[0])("commit metadata", True,
                                      f"{len(new_commits)} new commit(s), identity and "
                                      f"attribution verified from Git"))

        if self.config.publication.mode == "local_commit":
            self._transition(
                RunState.VERIFIED_LOCAL,
                f"committed {commit_sha[:12]} locally; the policy did not authorise a push",
            )
            self._write_receipt(
                published=False, commit_sha=commit_sha, approved=approved, push=None,
                checks=[c.to_dict() for c in checks], ci_status="not_triggered",
                new_commits=new_commits, tree=tree_sha,
            )
            return RunState.VERIFIED_LOCAL

        self._transition(RunState.PUSH, "publishing the verified branch")
        branch = publisher.branch_name(self.spec["phase_id"])
        try:
            push = publisher.push(self.candidate_dir, commit_sha=commit_sha, branch=branch)
        except PublicationRefusal as refusal:
            self._write_receipt(
                published=False, commit_sha=commit_sha, approved=approved, push=None,
                checks=[*(c.to_dict() for c in checks), *refusal.checks],
                ci_status="not_triggered", new_commits=new_commits, tree=tree_sha,
                notes=[str(refusal),
                       "the verified local commit is preserved; nothing was overwritten"],
            )
            raise

        self._write_receipt(
            published=True, commit_sha=commit_sha, approved=approved, push=push,
            checks=[*(c.to_dict() for c in checks), *push["checks"]],
            ci_status="not_triggered", new_commits=new_commits, tree=tree_sha,
            notes=[
                "this repository's CI runs on pushes to main/master and on pull requests. "
                "A pushed feature branch with no pull request has not been tested by CI; "
                "the push succeeding is not evidence that CI passed.",
                *self.notes,
            ],
        )
        self._transition(
            RunState.COMPLETE,
            f"published {commit_sha[:12]} to {push['remote']}/{branch}; the remote ref was "
            f"read back and matched",
        )
        return RunState.COMPLETE

    def _compose_message(self) -> tuple[str, str]:
        """The publisher composes this. No model writes this repository's history."""
        assert self.spec is not None
        requirement_lines = "\n".join(
            f"- {r['id']}: {r['statement']}" for r in self.spec["requirements"][:12]
        )
        evidence = self.store.evidence_for(
            self.run_id, candidate_fingerprint=self.candidate_fingerprint
        )
        passing = sorted({e["verification_id"] for e in evidence if e["outcome"] == "pass"})
        subject = f"{self.spec['phase_title']}"
        body = (
            f"{self.spec['summary']}\n\n{requirement_lines}\n\n"
            f"Verified: {', '.join(passing) if passing else 'no checks recorded'}."
        )
        return subject, body

    def _write_receipt(self, *, published: bool, commit_sha: str | None, approved: str | None,
                       push: dict | None, checks: list[dict], ci_status: str,
                       new_commits: list[dict], tree: str | None = None,
                       notes: list[str] | None = None) -> None:
        publisher = Publisher(
            repo_root=self.repo_root, policy=self.config.publication, run_id=self.run_id,
        )
        receipt = publisher.receipt(
            published=published, base_commit=self.base_commit, commit_sha=commit_sha,
            tree_fingerprint_value=getattr(self, "candidate_fingerprint", None),
            approved_fingerprint=approved,
            branch=(push or {}).get("branch"), remote=(push or {}).get("remote"),
            remote_url=(push or {}).get("remote_url"),
            remote_sha=(push or {}).get("remote_sha"),
            new_commits=new_commits, checks=checks, ci_status=ci_status,
            notes=notes or self.notes,
        )
        del tree
        write_json_atomic(self.run_dir / "publication-receipt.json", receipt)
        self.store.put_json_artifact(self.run_id, "publication_receipt", receipt)

    # ---------------------------------------------------------- provider call
    def _call_provider(
        self, adapter, *, role: str, prompt: str, cwd: Path, timeout: float,
        schema_id: str | None, system_prompt: str, writable: bool = False,
        task_id: str | None = None, sandbox_roots: list[Path] | None = None,
    ) -> ProviderResult:
        """Call a provider with retries for the failures retrying can fix.

        A malformed or schema-invalid answer gets one reprompt that names the
        problem; auth, model availability and a missing executable are not
        retried, because retrying cannot fix them and a run that keeps trying
        looks like progress.
        """
        attempts = self.config.limits.provider_retries + 1
        current_prompt = prompt
        last: ProviderResult | None = None

        # The provider needs somewhere to write besides the checkout: a temp
        # directory and, for Codex, a scratch directory. Granting only the
        # worktree makes the CLI die on startup with no output at all.
        slug = role.replace(":", "-")
        provider_dir = self.run_dir / "provider" / slug
        provider_tmp = provider_dir.parent / "tmp"
        provider_dir.mkdir(parents=True, exist_ok=True)
        provider_tmp.mkdir(parents=True, exist_ok=True)

        # Claude Code's subscription login resolves through the operator's real
        # configuration directory: a fresh CLAUDE_CONFIG_DIR reports "Not logged
        # in" even when they are signed in, and copying the account record does
        # not help. This was tested rather than assumed. So a worker uses the
        # real directory, and the files that could change what happens in the
        # operator's *next* interactive session -- settings, plugins, agents,
        # commands, hooks -- are carved back out of the grant.
        claude_config = Path(
            os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
        )
        write_roots = [*(sandbox_roots or []), Path(cwd) / ".pw-dev-scratch",
                       provider_dir, provider_tmp]
        # The checkout's own Python environment is carved back out of the grant.
        # The controller later runs `<checkout>/.venv/bin/python` *itself*, with
        # the controller's own privileges and no sandbox, so a worker able to
        # rewrite that interpreter -- or the `.pth` that composes its
        # `sys.path` -- would be choosing what the controller executes. Seatbelt
        # applies the last matching rule, and `pw-dev doctor` proves at startup
        # that a carve-out inside a granted root is honoured.
        denials: list[Path] = [Path(root) / ".venv" for root in (sandbox_roots or [])]
        if isinstance(adapter, ClaudeCliAdapter):
            write_roots.append(claude_config)
            # extend, never assign: assigning dropped the `.venv` carve-out
            # above for the one adapter that actually writes, which is the only
            # adapter it mattered for.
            denials.extend(claude_config_denials(claude_config))

        wrapper = None
        if writable and sandbox_roots and self.isolation_mode == "enforced":
            wrapper = sandbox_wrapper(
                write_roots, self.run_dir / "sandbox" / f"{slug}.sb", denials,
            )
        if writable and wrapper is None and self.isolation_mode == "enforced":
            raise PolicyViolation(
                "isolation resolved to 'enforced' but no sandbox wrapper could be built; "
                "refusing to run a writing worker without the boundary"
            )
        if writable and self.isolation_mode == "supervised" and self.config.isolation.unattended \
                and not self.config.isolation.allow_supervised_unattended:
            raise PolicyViolation(
                f"this host cannot enforce a write boundary ({self.sandbox_support.describe()}) "
                f"and the run is unattended. Refusing to run writing workers: either run "
                f"supervised, or set isolation.allow_supervised_unattended after reading what "
                f"that means."
            )

        for attempt in range(1, attempts + 1):
            self._check_budget()
            kwargs = dict(
                role=role, prompt=current_prompt, cwd=cwd, timeout=timeout,
                schema_id=schema_id, writable=writable,
                max_output_bytes=self.config.limits.max_output_bytes,
                system_prompt=system_prompt, cancel_check=self._check_cancelled,
            )
            if isinstance(adapter, ClaudeCliAdapter):
                kwargs["config_dir"] = claude_config
                kwargs["tmp_dir"] = provider_tmp
                kwargs["sandbox_wrapper"] = wrapper
                kwargs["allowed_write_roots"] = sandbox_roots or []
            else:
                kwargs["scratch_dir"] = provider_dir

            result = adapter.invoke(**kwargs)
            last = result
            roles.record_usage(self.store, self.run_id, result, task_id=task_id)
            self.store.event(
                self.run_id, "provider.call",
                f"{result.summary()} (attempt {attempt}/{attempts})",
                task_id=task_id,
                payload={
                    "provider": result.provider, "role": role,
                    "failure_kind": result.failure_kind, "exit_status": result.exit_status,
                    "model": result.usage.model or result.resolved_model,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_usd": result.usage.cost_usd,
                    "cost_known": result.usage.cost_known,
                    # Without this, diagnosing a provider that exits non-zero
                    # with empty stdout means reproducing the call by hand.
                    "stderr_tail": result.stderr_tail[-1500:] or None,
                },
            )
            if result.ok:
                return result
            if result.failure_kind in FATAL:
                raise PolicyViolation(
                    f"{result.provider} cannot run this role: {result.failure_kind} — "
                    f"{result.detail}. This is not retried: no number of attempts fixes "
                    f"authentication or an unavailable model."
                )
            if result.failure_kind == FailureKind.CANCELLED:
                raise RunAborted(RunState.CANCELLED, "cancelled by the operator")
            if attempt >= attempts:
                break
            if result.failure_kind in (FailureKind.SCHEMA_INVALID, FailureKind.MALFORMED_OUTPUT):
                current_prompt = (
                    f"{prompt}\n\n---\n\nYour previous response was rejected:\n\n"
                    f"{result.detail}\n\nReturn only the JSON document, with no prose "
                    f"around it."
                )
            elif result.failure_kind in RETRYABLE:
                backoff = min(60.0, 5.0 * (2 ** (attempt - 1)))
                self.report(
                    f"  {result.provider}/{role}: {result.failure_kind}; retrying in "
                    f"{backoff:.0f}s"
                )
                time.sleep(backoff)
            else:
                break

        assert last is not None
        if last.failure_kind == FailureKind.TIMEOUT:
            raise LimitReached(
                f"{last.provider}/{role} did not answer within {timeout:.0f}s after "
                f"{attempts} attempt(s). The worktree is preserved and reconciled rather "
                f"than assumed untouched.",
                limit="per_task_seconds",
            )
        raise PolicyViolation(
            f"{last.provider}/{role} failed after {attempts} attempt(s): "
            f"{last.failure_kind} — {last.detail}"
        )
