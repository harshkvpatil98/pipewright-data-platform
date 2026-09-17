"""Dependency-aware dispatch with bounded parallelism.

Three rules decide whether a task may start:

1. **dependencies** — every `depends_on` task is integrated. A downstream task
   runs against a checkout that already contains its prerequisites, so the
   scheduler also reports which commit a task should branch from;
2. **write ownership** — two tasks whose `allowed_paths` overlap are never
   eligible at the same time, even when neither depends on the other. This is
   checked here rather than hoped for, because the alternative is discovering it
   as a merge conflict after both workers have finished;
3. **exclusive resources** — Alembic revision allocation, lockfile and shared
   dependency changes, and shared contract edits take a named lock. One holder
   at a time, run-wide.

Final integration is serialized the same way: it is a task with an exclusive
resource, not a special case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import PolicyViolation
from ..state.machine import TaskState
from ..workspace.guard import PathGuard

#: Resources the controller always serializes, whatever the plan says.
IMPLICIT_EXCLUSIVE = {
    "alembic": ("apps/api-gateway/alembic/**", "apps/api-gateway/alembic.ini"),
    "lockfile": ("package-lock.json", "**/package-lock.json", "rush.json",
                 "common/config/**", "**/pnpm-lock.yaml"),
    "contracts": ("packages/shared-types/**",),
}


@dataclass
class TaskNode:
    id: str
    title: str
    role: str
    depends_on: list[str]
    allowed_paths: list[str]
    forbidden_paths: list[str] = field(default_factory=list)
    exclusive_resources: list[str] = field(default_factory=list)
    verification_ids: list[str] = field(default_factory=list)
    state: TaskState = TaskState.PENDING

    def guard(self) -> PathGuard:
        return PathGuard(self.allowed_paths, self.forbidden_paths)

    def effective_resources(self) -> list[str]:
        """Declared resources plus the ones implied by the paths a task claims."""
        resources = set(self.exclusive_resources)
        for name, patterns in IMPLICIT_EXCLUSIVE.items():
            guard = PathGuard(list(patterns))
            for claimed in self.allowed_paths:
                probe = claimed.replace("**", "x").replace("*", "x").rstrip("/")
                try:
                    guard.check(probe)
                except Exception:  # noqa: BLE001 - non-match is the common case
                    continue
                resources.add(name)
                break
        return sorted(resources)


class Scheduler:
    """Decides what may run now, given what has finished and what is held."""

    def __init__(self, nodes: list[TaskNode], *, max_parallel: int) -> None:
        self.nodes = {node.id: node for node in nodes}
        self.max_parallel = max(1, max_parallel)
        self._validate()

    # ------------------------------------------------------------- validation
    def _validate(self) -> None:
        for node in self.nodes.values():
            unknown = [dep for dep in node.depends_on if dep not in self.nodes]
            if unknown:
                raise PolicyViolation(f"{node.id} depends on unknown task(s): {unknown}")
            if not node.allowed_paths:
                raise PolicyViolation(f"{node.id} declares no writable paths")
        cycle = self._find_cycle()
        if cycle:
            raise PolicyViolation("the task graph contains a cycle: " + " -> ".join(cycle))

    def _find_cycle(self) -> list[str] | None:
        colour: dict[str, int] = {}
        stack: list[str] = []

        def visit(node_id: str) -> list[str] | None:
            colour[node_id] = 1
            stack.append(node_id)
            for dep in self.nodes[node_id].depends_on:
                if colour.get(dep, 0) == 1:
                    return stack[stack.index(dep):] + [dep]
                if colour.get(dep, 0) == 0:
                    found = visit(dep)
                    if found:
                        return found
            colour[node_id] = 2
            stack.pop()
            return None

        for node_id in self.nodes:
            if colour.get(node_id, 0) == 0:
                found = visit(node_id)
                if found:
                    return found
        return None

    def overlapping_pairs(self) -> list[tuple[str, str, list[str]]]:
        """Concurrently eligible tasks that claim the same paths.

        Only reported for pairs with no dependency between them: a task that
        depends on another is meant to build on its files.
        """
        problems: list[tuple[str, str, list[str]]] = []
        ordered = sorted(self.nodes.values(), key=lambda n: n.id)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                if self._related(left.id, right.id):
                    continue
                shared = left.guard().overlaps(right.guard())
                if shared:
                    problems.append((left.id, right.id, shared))
        return problems

    def _related(self, left: str, right: str) -> bool:
        return self._reaches(left, right) or self._reaches(right, left)

    def _reaches(self, start: str, target: str) -> bool:
        seen: set[str] = set()
        frontier = [start]
        while frontier:
            current = frontier.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(self.nodes[current].depends_on)
        return False

    # -------------------------------------------------------------- dispatch
    def ready(self, *, done: set[str], running: set[str], held_resources: dict[str, str]) -> list[TaskNode]:
        """Tasks that may start right now, in a stable order."""
        slots = self.max_parallel - len(running)
        if slots <= 0:
            return []

        running_guards = [self.nodes[t].guard() for t in running if t in self.nodes]
        claimed = {resource for resource, holder in held_resources.items() if holder not in done}
        eligible: list[TaskNode] = []

        for node in sorted(self.nodes.values(), key=lambda n: (n.role != "contract", n.id)):
            if node.id in done or node.id in running:
                continue
            if node.state in (TaskState.DONE, TaskState.INTEGRATED, TaskState.CANCELLED):
                continue
            if any(dep not in done for dep in node.depends_on):
                continue
            guard = node.guard()
            if any(guard.overlaps(other) for other in running_guards):
                continue
            resources = node.effective_resources()
            if any(resource in claimed for resource in resources):
                continue
            if any(guard.overlaps(peer.guard()) for peer in eligible):
                continue
            if any(resource in {r for peer in eligible for r in peer.effective_resources()}
                   for resource in resources):
                continue
            eligible.append(node)
            if len(eligible) >= slots:
                break
        return eligible

    def prerequisite_commit(self, node: TaskNode, integration_commits: dict[str, str],
                            base_commit: str) -> str:
        """Which commit a task should start from.

        The latest integration checkpoint that contains all of this task's
        prerequisites — not the run's base. A task that depends on the contract
        task must see those contracts.
        """
        if not node.depends_on:
            return base_commit
        candidates = [integration_commits[dep] for dep in node.depends_on
                      if dep in integration_commits]
        if not candidates:
            return base_commit
        # Integration is serialized, so the most recent checkpoint contains all
        # of them; `integration_commits["__latest__"]` is that checkpoint.
        return integration_commits.get("__latest__", candidates[-1])

    def blocked_reason(self, node: TaskNode, *, done: set[str], running: set[str],
                       held_resources: dict[str, str]) -> str:
        missing = [dep for dep in node.depends_on if dep not in done]
        if missing:
            return f"waiting on {', '.join(missing)}"
        resources = [r for r in node.effective_resources() if r in held_resources]
        if resources:
            holders = ", ".join(f"{r} (held by {held_resources[r]})" for r in resources)
            return f"waiting on exclusive resource: {holders}"
        guard = node.guard()
        for other in running:
            if other in self.nodes and guard.overlaps(self.nodes[other].guard()):
                return f"write ownership overlaps the running task {other}"
        if len(running) >= self.max_parallel:
            return f"at the concurrency limit ({self.max_parallel} workers)"
        return "ready"

    def topological_order(self) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in seen:
                return
            seen.add(node_id)
            for dep in sorted(self.nodes[node_id].depends_on):
                visit(dep)
            order.append(node_id)

        for node_id in sorted(self.nodes):
            visit(node_id)
        return order


def nodes_from_spec(spec: dict) -> list[TaskNode]:
    return [
        TaskNode(
            id=task["id"], title=task["title"], role=task["role"],
            depends_on=list(task.get("depends_on", [])),
            allowed_paths=list(task.get("allowed_paths", [])),
            forbidden_paths=list(task.get("forbidden_paths", [])),
            exclusive_resources=list(task.get("exclusive_resources", [])),
            verification_ids=list(task.get("verification_ids", [])),
        )
        for task in spec["tasks"]
    ]


def scope_union(spec: dict) -> list[str]:
    """Every path the specification permits anyone to write. Used at publication."""
    paths: set[str] = set()
    for task in spec["tasks"]:
        paths.update(task.get("allowed_paths", []))
    return sorted(paths)
