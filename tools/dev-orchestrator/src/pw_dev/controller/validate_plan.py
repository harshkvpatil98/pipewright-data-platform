"""VALIDATE_PLAN: the controller checks the planner's proposal before anyone works.

The planner is a model. Its output is a proposal, and this is where the proposal
meets the adopted policy. Everything checked here is cheaper to catch now than
after three workers have run: an unknown verification ID, two tasks that claim
the same files, a path scope reaching into `.git`, a limit above what the
operator adopted, or a publication policy the plan invented for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..schemas.validate import SchemaError, validate_artifact
from ..verify.registry import Registry
from ..workspace.guard import ALWAYS_FORBIDDEN, PathGuard, PathViolation, normalise
from .scheduler import Scheduler, nodes_from_spec


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
        return "\n".join(lines) or "  (no findings)"


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

    task_ids: set[str] = set()
    for task in spec["tasks"]:
        if task["id"] in task_ids:
            report.errors.append(f"duplicate task id {task['id']!r}")
        task_ids.add(task["id"])

        unknown_requirements = sorted(set(task["requirement_ids"]) - requirement_ids)
        if unknown_requirements:
            report.errors.append(
                f"{task['id']} references requirement ids that do not exist: {unknown_requirements}"
            )

        unknown_checks = registry.validate_ids(task["verification_ids"])
        if unknown_checks:
            report.errors.append(
                f"{task['id']} requests unregistered verification ids {unknown_checks}. "
                f"Agents request ids; they do not supply commands."
            )

        if not task["allowed_paths"]:
            report.errors.append(f"{task['id']} declares no writable paths")
        for raw in task["allowed_paths"]:
            probe = raw.replace("**", "x").replace("*", "x").rstrip("/")
            try:
                normalise(probe)
            except PathViolation as violation:
                report.errors.append(f"{task['id']} allowed_path {raw!r}: {violation.reason}")
                continue
            try:
                PathGuard([raw]).check(probe)
            except PathViolation as violation:
                if any(pattern in violation.reason for pattern in ALWAYS_FORBIDDEN):
                    report.errors.append(
                        f"{task['id']} claims {raw!r}, which is never writable by a task "
                        f"({violation.reason})"
                    )

        if repo_root is not None:
            for raw in task["context_paths"]:
                try:
                    relative = normalise(raw)
                except PathViolation as violation:
                    report.errors.append(f"{task['id']} context_path {raw!r}: {violation.reason}")
                    continue
                if not (Path(repo_root) / relative).exists():
                    report.warnings.append(
                        f"{task['id']} asks for context file {relative!r}, which is not in "
                        f"this checkout"
                    )

    unknown_required = registry.validate_ids(spec["required_verifications"])
    if unknown_required:
        report.errors.append(
            f"required_verifications names unregistered ids {unknown_required}"
        )
    gate_ids = {check.id for check in registry.gates()}
    missing_gates = sorted(gate_ids - set(spec["required_verifications"]))
    if missing_gates:
        report.warnings.append(
            f"the plan omits gate checks {missing_gates}; the controller runs them anyway "
            f"before COMMIT"
        )

    for criterion in spec["acceptance_criteria"]:
        unknown = sorted(set(criterion["requirement_ids"]) - requirement_ids)
        if unknown:
            report.errors.append(
                f"acceptance criterion {criterion['id']} references unknown requirements {unknown}"
            )

    limits = spec["resource_limits"]
    if limits["max_parallel_workers"] > config.limits.max_parallel_workers:
        report.errors.append(
            f"the plan asks for {limits['max_parallel_workers']} parallel workers; the "
            f"adopted limit is {config.limits.max_parallel_workers}. A plan does not raise "
            f"its own budget."
        )
    if limits["total_run_seconds"] > config.limits.total_run_seconds:
        report.errors.append(
            f"the plan asks for {limits['total_run_seconds']}s of wall clock; the adopted "
            f"limit is {config.limits.total_run_seconds}s"
        )
    if limits["repair_rounds_per_task"] > config.limits.repair_rounds_per_task:
        report.errors.append(
            f"the plan asks for {limits['repair_rounds_per_task']} repair rounds; the "
            f"adopted limit is {config.limits.repair_rounds_per_task}"
        )

    policy = spec["publication_policy"]
    if policy["mode"] != config.publication.mode:
        report.errors.append(
            f"the plan declares publication mode {policy['mode']!r}; this run adopted "
            f"{config.publication.mode!r}. Publication authority comes from the run policy, "
            f"not from the plan."
        )
    if policy["allow_existing_branch"] and policy["allow_existing_branch"] != (
        config.publication.allow_existing_branch
    ):
        report.errors.append(
            f"the plan selects the existing branch {policy['allow_existing_branch']!r}, "
            f"which this run's policy did not authorise"
        )

    try:
        scheduler = Scheduler(nodes_from_spec(spec), max_parallel=limits["max_parallel_workers"])
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        report.errors.append(str(exc))
        return report

    for left, right, shared in scheduler.overlapping_pairs():
        report.errors.append(
            f"{left} and {right} have no dependency between them but both claim "
            f"{'; '.join(shared[:3])}. Concurrently eligible tasks may not share write "
            f"ownership: add a dependency, or split the paths."
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
