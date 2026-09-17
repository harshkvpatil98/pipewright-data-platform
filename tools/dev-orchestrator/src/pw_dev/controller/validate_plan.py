"""VALIDATE_PLAN: the controller checks the planner's proposal before anyone works.

The planner is a model. Its output is a proposal, and this is where the proposal
meets the adopted policy. Everything checked here is cheaper to catch now than
after three workers have run: an unknown verification ID, two tasks that claim
the same files, a path scope reaching into `.git`, a limit above what the
operator adopted, or a publication policy the plan invented for itself.

## What passing this does and does not establish

It establishes that the document is well-formed; that every identifier it uses
resolves; that its paths are writable, unambiguous, and not claimed twice by
tasks that could run at once; that its budgets are inside the adopted ones; and
that its publication policy is the one this run holds.

It establishes **nothing** about whether the design is correct, whether the
tasks add up to the requirements, or whether the phase is the right one. Those
are read by a reviewer and settled by executed verification. `CAVEAT` is printed
with every report so a green validation is not quoted as an approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..schemas.validate import SchemaError, validate_artifact
from ..verify.registry import Registry
from ..workspace.guard import (ALWAYS_FORBIDDEN, PathGuard, PathViolation, is_pattern,
                               normalise, patterns_overlap)
from .scheduler import Scheduler, nodes_from_spec

CAVEAT = (
    "validation checks structure, identifiers, path scope, budgets and policy. It does "
    "not establish that the design is correct, that the tasks cover the requirements, or "
    "that the phase is the right one -- a reviewer and executed verification do that."
)

#: A path that looks like it holds tests. Used to report a task that owns
#: implementation files and no test files, which is a finding a human can act
#: on rather than a rule the controller enforces.
_TEST_MARKERS = ("tests/", "/tests/", "__tests__", ".test.", ".spec.", "test_")


@dataclass
class PlanReport:
    """Whether a specification may be executed, and what is wrong with it."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = []
        for error in self.errors:
            lines.append(f"  error:   {error}")
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        lines.append(f"  note:    {CAVEAT}")
        return "\n".join(lines)


def _looks_like_tests(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _TEST_MARKERS)


def validate_plan(
    spec: dict, *, config: Config, registry: Registry, base_commit: str,
    repo_root: Path | None = None,
) -> PlanReport:
    report = PlanReport()

    try:
        validate_artifact(spec, "phase_spec/v1")
    except SchemaError as exc:
        report.errors.extend(exc.errors)
        return report  # nothing below can be trusted about a malformed document

    if spec["base_commit"] != base_commit:
        report.errors.append(
            f"the plan was written against {spec['base_commit'][:12]} but this run's base is "
            f"{base_commit[:12]}. Replan, or resume the run that matches."
        )

    if not spec["requirements"]:
        report.errors.append("the plan states no requirements")
    if not spec["tasks"]:
        report.errors.append("the plan contains no tasks")
    if not spec["source_references"]:
        report.warnings.append(
            "the plan cites no source references; every claim about existing behaviour "
            "is unverified"
        )

    requirement_ids = {r["id"] for r in spec["requirements"]}
    duplicates = len(spec["requirements"]) - len(requirement_ids)
    if duplicates:
        report.errors.append(f"{duplicates} requirement id(s) are duplicated")

    _check_tasks(spec, report, registry=registry, requirement_ids=requirement_ids,
                 repo_root=repo_root)
    _check_verification_references(spec, report, registry=registry)
    _check_traceability(spec, report, requirement_ids=requirement_ids)
    _check_limits(spec, report, config=config)
    _check_publication(spec, report, config=config)
    _check_migrations(spec, report)

    limits = spec["resource_limits"]
    try:
        scheduler = Scheduler(
            nodes_from_spec(spec), max_parallel=max(1, limits["max_parallel_workers"]),
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        report.errors.append(str(exc))
        return report

    for left, right, shared in scheduler.overlapping_pairs():
        report.errors.append(
            f"{left} and {right} have no dependency between them but both claim "
            f"{'; '.join(shared[:3])}. Concurrently eligible tasks may not share write "
            f"ownership: add a dependency, or split the paths."
        )

    for node in scheduler.nodes.values():
        for reach in node.unguarded_resource_reach():
            report.warnings.append(
                f"{node.id} can write the serialized resource {reach} without holding the "
                f"lock, because its claim overlaps that territory without being contained "
                f"in it. Narrow the paths, or declare the resource."
            )

    contract_tasks = [t["id"] for t in spec["tasks"] if t["role"] == "contract"]
    if contract_tasks:
        for task in spec["tasks"]:
            if task["role"] in ("backend", "frontend") and not any(
                dep in contract_tasks for dep in task["depends_on"]
            ):
                report.warnings.append(
                    f"{task['id']} ({task['role']}) does not depend on any contract task; "
                    f"check that it does not need {contract_tasks}"
                )

    if not spec["non_goals"]:
        report.warnings.append(
            "the plan lists no non-goals; a phase with no stated boundary is hard to review"
        )
    if not spec["risks"]:
        report.warnings.append("the plan lists no risks")

    return report


# ----------------------------------------------------------------------- tasks
def _check_tasks(spec: dict, report: PlanReport, *, registry: Registry,
                 requirement_ids: set[str], repo_root: Path | None) -> None:
    task_ids: set[str] = set()
    for task in spec["tasks"]:
        if task["id"] in task_ids:
            report.errors.append(f"duplicate task id {task['id']!r}")
        task_ids.add(task["id"])

        unknown_requirements = sorted(set(task["requirement_ids"]) - requirement_ids)
        if unknown_requirements:
            report.errors.append(
                f"{task['id']} references requirement ids that do not exist: "
                f"{unknown_requirements}"
            )

        unknown_checks = registry.validate_ids(task["verification_ids"])
        if unknown_checks:
            report.errors.append(
                f"{task['id']} requests unregistered verification ids {unknown_checks}. "
                f"Agents request ids; they do not supply commands."
            )

        if not task["allowed_paths"]:
            if task["role"] != "verification":
                report.errors.append(
                    f"{task['id']} ({task['role']}) declares no writable paths. A worker "
                    f"that owns nothing cannot produce a patch, and the controller has no "
                    f"scope against which to judge what it did. Only a 'verification' task "
                    f"may own nothing; the controller then executes it itself."
                )
            elif not task["verification_ids"]:
                report.errors.append(
                    f"{task['id']} is a verification task that owns nothing and names no "
                    f"verification_ids, so it would do nothing at all. Give it the checks "
                    f"it exists to run, or remove it."
                )

        _check_task_paths(task, report)

        if repo_root is not None:
            for raw in task["context_paths"]:
                try:
                    relative = normalise(raw)
                except PathViolation as violation:
                    report.errors.append(
                        f"{task['id']} context_path {raw!r}: {violation.reason}")
                    continue
                if not (Path(repo_root) / relative).exists():
                    report.warnings.append(
                        f"{task['id']} asks for context file {relative!r}, which is not in "
                        f"this checkout"
                    )

        if task["role"] == "verification" and task["verification_ids"]:
            required = set(spec["required_verifications"])
            unrequired = [c for c in task["verification_ids"] if c not in required]
            if unrequired:
                report.warnings.append(
                    f"{task['id']} is a checkpoint whose checks {sorted(unrequired)} are not "
                    f"in required_verifications. They will gate this task's dependents, but "
                    f"nothing re-runs them against the final candidate before COMMIT."
                )

        if task["role"] in ("backend", "frontend", "contract"):
            if not any(_looks_like_tests(p) for p in task["allowed_paths"]):
                report.warnings.append(
                    f"{task['id']} ({task['role']}) owns implementation paths and no test "
                    f"path. Whoever verifies its requirements cannot add a test inside its "
                    f"scope, so either give it test ownership or name the task that has it."
                )


def _check_task_paths(task: dict, report: PlanReport) -> None:
    """Every declared path, against the guard that will actually judge it.

    The concrete ones are run through `PathGuard.check` exactly as the
    integration diff will be, so a path the specification promises a worker and
    the guard then refuses is a planning error rather than a wasted round. A
    pattern cannot be `check`ed -- it is not a path -- so it is tested for
    overlap with the standing forbidden set and with the task's own exclusions.
    """
    guard = PathGuard(task["allowed_paths"], task["forbidden_paths"])

    for raw in task["allowed_paths"]:
        try:
            probe = normalise(raw.replace("**", "x").replace("*", "x").replace("?", "x"))
        except PathViolation as violation:
            report.errors.append(f"{task['id']} allowed_path {raw!r}: {violation.reason}")
            continue

        # Containment, not intersection. `services/x/tests/**` intersects the
        # standing `**/.env` rule -- a `.env` could exist under it -- and that
        # is not a planning error: the guard refuses that one file and the task
        # keeps the rest. What is an error is claiming the forbidden territory
        # itself, or a scope that swallows it whole.
        forbidden_hit = next(
            (pattern for pattern in ALWAYS_FORBIDDEN
             if _covers_completely(pattern, raw) or _covers_completely(raw, pattern)), None)
        if forbidden_hit is not None:
            report.errors.append(
                f"{task['id']} claims {raw!r}, which is or contains {forbidden_hit!r} -- "
                f"never writable by a task in any run (controller state, credentials, Git "
                f"metadata, CI configuration and the verification/publication code)"
            )
            continue

        own_hit = next(
            (pattern for pattern in task["forbidden_paths"]
             if patterns_overlap(raw, pattern) and _covers_completely(pattern, raw)), None)
        if own_hit is not None:
            report.errors.append(
                f"{task['id']} declares {raw!r} writable and then forbids all of it with "
                f"{own_hit!r}. The task cannot write what it was given."
            )
            continue

        if not is_pattern(raw):
            try:
                guard.check(probe)
            except PathViolation as violation:
                report.errors.append(
                    f"{task['id']} declares {raw!r} but the path guard refuses it: "
                    f"{violation.reason}"
                )

    # A `forbidden_paths` entry naming another task's territory is a legible
    # convention in this repository's plans, not a mistake, so it is not
    # reported. The case worth an error -- an exclusion that swallows the
    # task's own scope -- is handled above.


def _implicit_resources(task: dict) -> list[str]:
    from .scheduler import TaskNode

    return TaskNode(
        id=task["id"], title=task["title"], role=task["role"], depends_on=[],
        allowed_paths=list(task["allowed_paths"]),
    ).effective_resources()


def _covers_completely(outer: str, inner: str) -> bool:
    from ..workspace.guard import pattern_covers

    return pattern_covers(outer, inner)


# -------------------------------------------------------------- verifications
def _check_verification_references(spec: dict, report: PlanReport, *,
                                   registry: Registry) -> None:
    unknown_required = registry.validate_ids(spec["required_verifications"])
    if unknown_required:
        report.errors.append(
            f"required_verifications names unregistered ids {unknown_required}"
        )

    for criterion in spec["acceptance_criteria"]:
        unknown = registry.validate_ids(criterion["verification_ids"])
        if unknown:
            report.errors.append(
                f"acceptance criterion {criterion['id']} names unregistered verification "
                f"ids {unknown}"
            )

    for entry in spec["accepted_preexisting_failures"]:
        check_id = entry["verification_id"]
        if registry.validate_ids([check_id]):
            report.errors.append(
                f"accepted_preexisting_failures names the unregistered verification "
                f"{check_id!r}"
            )
            continue
        if registry.get(check_id).evidence_class == "required_live":
            report.errors.append(
                f"accepted_preexisting_failures scopes out {check_id!r}, a required live "
                f"acceptance path. Its scenario does not exist until this phase writes it, "
                f"so it is non-passing at baseline by construction: scoping it out waives "
                f"the gate rather than recording a pre-existing failure. Write the "
                f"scenario, or stop requiring the check."
            )

    gate_ids = {check.id for check in registry.gates()}
    missing_gates = sorted(gate_ids - set(spec["required_verifications"]))
    if missing_gates:
        report.warnings.append(
            f"the plan omits gate checks {missing_gates}; the controller runs them anyway "
            f"before COMMIT"
        )

    declared = set(spec["required_verifications"])
    for task in spec["tasks"]:
        for check_id in task["verification_ids"]:
            check = registry.get(check_id) if check_id in registry else None
            if check is not None and check.evidence_class == "required_live" \
                    and check_id not in declared:
                report.errors.append(
                    f"{task['id']} requests {check_id!r}, a required live acceptance path, "
                    f"but the plan does not list it in required_verifications. A live "
                    f"scenario that only one task asks for is not a gate on the phase."
                )

    live_ids = {check.id for check in registry.of_class("required_live")}
    smoke_ids = {check.id for check in registry.of_class("optional_smoke")}
    if declared & smoke_ids and not declared & live_ids:
        report.warnings.append(
            f"required_verifications relies on {sorted(declared & smoke_ids)}, which is an "
            f"optional diagnostic: it exits 0 offline and is satisfied by any server "
            f"answering the configured root. If this phase promises an authenticated "
            f"end-to-end workflow, require {sorted(live_ids)} as well."
        )


def _check_traceability(spec: dict, report: PlanReport, *,
                        requirement_ids: set[str]) -> None:
    criterion_ids: set[str] = set()
    for criterion in spec["acceptance_criteria"]:
        if criterion["id"] in criterion_ids:
            report.errors.append(f"duplicate acceptance criterion id {criterion['id']!r}")
        criterion_ids.add(criterion["id"])
        unknown = sorted(set(criterion["requirement_ids"]) - requirement_ids)
        if unknown:
            report.errors.append(
                f"acceptance criterion {criterion['id']} references unknown requirements "
                f"{unknown}"
            )

    owned = {rid for task in spec["tasks"] for rid in task["requirement_ids"]}
    unowned = sorted(requirement_ids - owned)
    if unowned:
        report.errors.append(
            f"no task owns requirement(s) {unowned}. Every requirement needs a task that "
            f"delivers it, or it should be a non-goal."
        )

    covered = {rid for c in spec["acceptance_criteria"] for rid in c["requirement_ids"]}
    uncovered = sorted(requirement_ids - covered)
    if uncovered:
        report.warnings.append(
            f"requirement(s) {uncovered} have no acceptance criterion, so nothing states "
            f"how their delivery would be recognised"
        )

    unverified = sorted(
        c["id"] for c in spec["acceptance_criteria"] if not c["verification_ids"]
    )
    if unverified:
        report.warnings.append(
            f"acceptance criteria {unverified} name no verification, so they are assertions "
            f"rather than things the controller can check"
        )


# ---------------------------------------------------------------------- limits
def _check_limits(spec: dict, report: PlanReport, *, config: Config) -> None:
    limits = spec["resource_limits"]
    adopted = config.limits

    if limits["max_parallel_workers"] < 1:
        report.errors.append("the plan asks for fewer than one worker")
    if limits["max_parallel_workers"] > adopted.max_parallel_workers:
        report.errors.append(
            f"the plan asks for {limits['max_parallel_workers']} parallel workers; the "
            f"adopted limit is {adopted.max_parallel_workers}. A plan does not raise "
            f"its own budget."
        )
    if limits["per_task_seconds"] > adopted.per_task_seconds:
        report.errors.append(
            f"the plan asks for {limits['per_task_seconds']}s per task; the adopted limit "
            f"is {adopted.per_task_seconds}s"
        )
    if limits["total_run_seconds"] > adopted.total_run_seconds:
        report.errors.append(
            f"the plan asks for {limits['total_run_seconds']}s of wall clock; the adopted "
            f"limit is {adopted.total_run_seconds}s"
        )
    if limits["repair_rounds_per_task"] > adopted.repair_rounds_per_task:
        report.errors.append(
            f"the plan asks for {limits['repair_rounds_per_task']} repair rounds; the "
            f"adopted limit is {adopted.repair_rounds_per_task}"
        )

    if limits["per_task_seconds"] > limits["total_run_seconds"]:
        report.errors.append(
            f"one task may run for {limits['per_task_seconds']}s and the whole run for "
            f"{limits['total_run_seconds']}s, so the first task can exhaust the run. "
            f"Budget exhaustion produces PAUSED, not a finished phase."
        )

    # `per_task_seconds` is a *timeout*, not an estimate: a task that finishes in
    # a minute does not consume thirty, so no arithmetic over it predicts a
    # duration. What it bounds is the worst case, and the useful question is
    # whether even the *unavoidable* part of that worst case fits.
    #
    # Three things force provider calls apart, and the largest is the bound:
    #
    #   * a dependency chain -- no number of workers shortens it;
    #   * worker capacity -- W workers run at most W calls at once, so N tasks
    #     need at least ceil(N / W) waves. This is a perfectly good *lower*
    #     bound; it was only ever wrong when quoted as a ceiling, because a
    #     chain can force more waves than capacity does;
    #   * an exclusive resource -- one holder at a time, run-wide.
    #
    # Only tasks that dispatch a worker are counted. A controller-executed
    # checkpoint consumes check time, not a provider timeout, and charging it
    # one would invent work nobody does. Environment preparation, controller
    # verification, integration and review are excluded too -- said plainly,
    # rather than folded in as though they were free.
    worker_tasks = [t for t in spec["tasks"]
                    if not (t["role"] == "verification" and not t["allowed_paths"])]
    per_task = limits["per_task_seconds"]
    workers = max(1, limits["max_parallel_workers"])
    counted = {t["id"] for t in worker_tasks}

    chain, chain_path = _longest_chain(spec, counted)
    resource, resource_count = _largest_serialized_resource(worker_tasks)
    capacity = -(-len(worker_tasks) // workers)

    reasons = [
        (chain, f"a dependency chain of {chain} worker task(s)"
                + (f" ({' -> '.join(chain_path)})" if chain_path else "")),
        (capacity, f"{len(worker_tasks)} worker task(s) across {workers} worker(s), "
                   f"so {capacity} wave(s)"),
        (resource_count, f"{resource_count} task(s) serialized on the {resource!r} "
                         f"resource"),
    ]
    rounds, why = max(reasons, key=lambda item: item[0])
    floor = rounds * per_task

    controller_only = len(spec["tasks"]) - len(worker_tasks)
    excluded = ("environment preparation, controller verification, integration and review"
                + (f", and {controller_only} controller-executed checkpoint(s) that "
                   f"consume no provider call" if controller_only else ""))

    if floor > limits["total_run_seconds"]:
        report.errors.append(
            f"{why} cannot overlap, so in the worst case that alone needs {floor}s of "
            f"provider time against the plan's {limits['total_run_seconds']}s -- before "
            f"{excluded}, or any of the {limits['repair_rounds_per_task']} repair "
            f"round(s). Split the work, or plan for a run that pauses and resumes: "
            f"exhausting the budget produces PAUSED with the work preserved, never a "
            f"finished phase."
        )
    elif floor > limits["total_run_seconds"] * 0.5:
        report.warnings.append(
            f"the largest unavoidable serialization here is {why}; at the full per-task "
            f"timeout that is {floor}s of the plan's {limits['total_run_seconds']}s, "
            f"before {excluded}. That is a worst case, not a prediction, but there is "
            f"little room in it: plan resumable checkpoints and expect PAUSED rather "
            f"than completion."
        )


def _longest_chain(spec: dict, counted: set[str] | None = None) -> tuple[int, list[str]]:
    """The most provider calls that must happen one after another, and the path.

    Dependencies are the part of a schedule no number of workers removes.
    `counted` restricts what contributes to the length -- a controller-executed
    checkpoint still orders the tasks around it and still costs no provider
    call -- while staying in the reported path so the chain reads correctly.
    """
    tasks = {t["id"]: list(t["depends_on"]) for t in spec["tasks"]}
    if counted is None:
        counted = set(tasks)
    memo: dict[str, list[str]] = {}

    def longest(task_id: str, seen: frozenset) -> list[str]:
        if task_id in memo:
            return memo[task_id]
        if task_id in seen:
            # A cycle. The scheduler refuses the plan for it separately; what
            # must not happen here is inventing a chain out of the loop, which
            # reported `A -> B -> A` as three serial tasks.
            raise _Cycle(task_id)
        best: list[str] = []
        for parent in tasks.get(task_id, ()):
            if parent not in tasks:
                continue
            candidate = longest(parent, seen | {task_id})
            if _weight(candidate, counted) > _weight(best, counted):
                best = candidate
        path = [*best, task_id]
        memo[task_id] = path
        return path

    longest_path: list[str] = []
    for task_id in tasks:
        try:
            path = longest(task_id, frozenset())
        except _Cycle:
            return 0, []
        if _weight(path, counted) > _weight(longest_path, counted):
            longest_path = path
    return _weight(longest_path, counted), longest_path


def _weight(path: list[str], counted: set[str]) -> int:
    """How many provider calls a path costs. A controller-executed checkpoint
    orders the work around it and consumes no provider call, so it counts zero."""
    return sum(1 for task_id in path if task_id in counted)


class _Cycle(Exception):
    """The graph loops. Reported by the scheduler; never turned into a chain."""


def _largest_serialized_resource(tasks: list[dict]) -> tuple[str, int]:
    """The exclusive resource held by the most tasks, and how many hold it.

    One holder at a time, run-wide, so these tasks cannot overlap either --
    whatever the dependency graph says.
    """
    counts: dict[str, int] = {}
    for task in tasks:
        declared = set(task["exclusive_resources"]) | set(_implicit_resources(task))
        for resource in declared:
            counts[resource] = counts.get(resource, 0) + 1
    if not counts:
        return "none", 0
    name = max(counts, key=lambda key: (counts[key], key))
    return name, counts[name]


def _check_publication(spec: dict, report: PlanReport, *, config: Config) -> None:
    policy = spec["publication_policy"]
    if policy["mode"] != config.publication.mode:
        report.errors.append(
            f"the plan declares publication mode {policy['mode']!r}; this run adopted "
            f"{config.publication.mode!r}. Publication authority comes from the run policy, "
            f"not from the plan. Produce the specification under the policy it will run "
            f"under -- `pw-dev plan --publish {_flag(config.publication.mode)}` -- and "
            f"execute it with the same `--publish` value. Neither the frozen policy of a "
            f"recorded run nor this equality check is edited to make an existing "
            f"specification fit."
        )
    if policy["allow_existing_branch"] and policy["allow_existing_branch"] != (
        config.publication.allow_existing_branch
    ):
        report.errors.append(
            f"the plan selects the existing branch {policy['allow_existing_branch']!r}, "
            f"which this run's policy did not authorise"
        )
    if policy["branch_prefix"] != config.publication.branch_prefix:
        report.errors.append(
            f"the plan names branch prefix {policy['branch_prefix']!r}; this run adopted "
            f"{config.publication.branch_prefix!r}, and the publisher uses the adopted one. "
            f"`publication_policy` is the policy this specification was written for, so a "
            f"prefix the run will not use is a disagreement, not a note: a reviewer reading "
            f"the specification would expect a branch that never appears."
        )


def _flag(mode: str) -> str:
    return {"none": "none", "local_commit": "local", "feature_branch": "feature-branch"}.get(
        mode, mode)


def _check_migrations(spec: dict, report: PlanReport) -> None:
    strategy = spec["migration_strategy"]
    if not strategy or not strategy.get("needed"):
        return
    revisions = strategy.get("alembic_revisions") or []
    if not revisions:
        report.warnings.append(
            "migration_strategy says a migration is needed but names no revision slug, so "
            "the controller cannot tell which task allocates it"
        )
    # Ownership and serialization are different questions, and a task can hold
    # the lock without being able to write the file. Declaring
    # `exclusive_resources: ["alembic"]` beside `allowed_paths: ["src/app.py"]`
    # used to satisfy this check while guaranteeing the revision could never be
    # created.
    owners = [
        task["id"] for task in spec["tasks"]
        if any(patterns_overlap(p, "apps/api-gateway/alembic/versions/**")
               for p in task["allowed_paths"])
    ]
    if not owners:
        report.errors.append(
            "migration_strategy declares a migration, but no task's allowed_paths reach "
            "apps/api-gateway/alembic/versions/**. A task that cannot write the revision "
            "file cannot allocate the revision, whatever resource it declares."
        )
    else:
        unlocked = [
            task_id for task_id in owners
            if "alembic" not in next(
                t for t in spec["tasks"] if t["id"] == task_id)["exclusive_resources"]
        ]
        for task_id in unlocked:
            node = next(t for t in spec["tasks"] if t["id"] == task_id)
            if "alembic" not in _implicit_resources(node):
                report.warnings.append(
                    f"{task_id} owns Alembic revision paths without declaring the "
                    f"'alembic' resource; the controller infers the lock from the paths, "
                    f"but declaring it makes the serialization visible in the plan"
                )
        if len(owners) > 1:
            report.warnings.append(
                f"tasks {owners} each own Alembic revision paths. The controller "
                f"serializes them, but two revisions allocated from one parent is exactly "
                f"what alembic:heads refuses."
            )
    for revision in revisions:
        if not any(any(revision in p for p in task["allowed_paths"]) for task in spec["tasks"]):
            report.warnings.append(
                f"no task's allowed_paths name the declared revision slug {revision!r}, so "
                f"which file will carry it is not stated in the plan"
            )
