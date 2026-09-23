"""Semantics-preserving rewrites of an IR tree (Phase 22 groundwork).

Phase 12 decides *where* a tree runs; this file makes small, provable changes
to the tree first so that more of it can run at the source. Every rewrite
here is a textbook algebraic identity, and every one is covered by the
differential test: the tree before and the tree after are executed by both
backends and must agree value for value.

**What is here, and why each one is safe**

- *Predicate pushdown through a row-wise node.* ``Filter(Project(x))`` becomes
  ``Project(Filter(x))`` when every column the predicate reads is passed
  through the projection unchanged (a bare column under its own name). A
  projection is one output row per input row, so the filter sees the same
  values either way. ``Filter(Sort(x))`` becomes ``Sort(Filter(x))`` because a
  filter keeps the relative order of what it keeps.
- *Limit pushdown through a projection.* ``Limit(Project(x))`` becomes
  ``Project(Limit(x))``: a projection neither adds, drops nor reorders rows.
  A limit is **never** moved below a sort, a filter, a distinct or an
  aggregate -- each of those changes which rows exist.
- *Adjacent filter merge.* ``Filter(Filter(x, a), b)`` becomes
  ``Filter(x, a AND b)``. Under three-valued logic ``a AND b`` is true exactly
  when both are true, which is the only case the pair kept.
- *Adjacent limit merge.* ``Limit(Limit(x, n1, o1), n2, o2)`` becomes one limit
  with offset ``o1 + o2`` and count ``min(n1 - o2, n2)`` (either may be
  absent). Rows ``[o1, o1+n1)`` then ``[o2, o2+n2)`` of that is exactly the
  merged window.

**What is deliberately not here.** No constant folding (dialects disagree on
how expressions evaluate at the edges), no join reordering (needs statistics
this platform does not collect yet), no projection pruning (the pandas
backend and lineage both want the columns a user asked for), nothing that
looks at an ``Extension`` (its semantics are unknown by construction, so
nothing moves through it).

The planner applies these before it splits the tree and reports what it did,
because a rewrite that silently changed a plan would be indistinguishable from
a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from service_transformations.ir.expressions import Call, Column
from service_transformations.ir.nodes import Filter, Limit, Node, Project, Sort


@dataclass(frozen=True)
class Rewrite:
    """One rewrite that was applied, in words a plan panel can show."""

    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.detail}"


def rewrite(node: Node) -> tuple[Node, list[Rewrite]]:
    """Apply every safe rewrite to a fixpoint, bottom-up.

    Returns the rewritten tree and what was done, in order. A tree nothing
    applies to comes back as the same object with an empty list.
    """
    applied: list[Rewrite] = []
    current = node
    for _ in range(
        64
    ):  # every rule strictly shrinks or lowers something; this is a guard
        changed, current = _pass(current, applied)
        if not changed:
            break
    return current, applied


def _pass(node: Node, applied: list[Rewrite]) -> tuple[bool, Node]:
    """One bottom-up pass. Children first so a rule sees already-lowered inputs."""
    changed = False
    rebuilt = node
    children = node.children()
    if children:
        new_children = []
        for child in children:
            child_changed, new_child = _pass(child, applied)
            changed = changed or child_changed
            new_children.append(new_child)
        if changed:
            rebuilt = _with_children(node, new_children)

    result = _rewrite_here(rebuilt, applied)
    if result is not None:
        return True, result
    return changed, rebuilt


def _with_children(node: Node, children: list[Node]) -> Node:
    if hasattr(node, "input"):
        return replace(node, input=children[0])  # type: ignore[arg-type]
    if hasattr(node, "left"):
        return replace(node, left=children[0], right=children[1])  # type: ignore[arg-type]
    return node  # pragma: no cover - every non-leaf node has one of the two


def _rewrite_here(node: Node, applied: list[Rewrite]) -> Node | None:
    if isinstance(node, Filter):
        below = node.input
        if isinstance(below, Filter):
            merged = Filter(below.input, Call("and", (below.predicate, node.predicate)))
            applied.append(
                Rewrite("merge filters", f"{below.predicate} AND {node.predicate}")
            )
            return merged
        if isinstance(below, Project) and _passes_through(
            below, node.predicate.columns_used()
        ):
            lowered = Project(Filter(below.input, node.predicate), below.projections)
            applied.append(
                Rewrite(
                    "filter below projection",
                    f"{node.predicate} now runs before {below}",
                )
            )
            return lowered
        if isinstance(below, Sort):
            lowered = Sort(Filter(below.input, node.predicate), below.keys)
            applied.append(
                Rewrite(
                    "filter below sort", f"{node.predicate} now runs before {below}"
                )
            )
            return lowered
        return None

    if isinstance(node, Limit):
        below = node.input
        if isinstance(below, Limit):
            merged = _merge_limits(below, node)
            applied.append(Rewrite("merge limits", f"{below} then {node} is {merged}"))
            return merged
        if isinstance(below, Project):
            lowered = Project(
                Limit(below.input, node.count, node.offset), below.projections
            )
            applied.append(
                Rewrite("limit below projection", f"{node} now runs before {below}")
            )
            return lowered
        return None

    return None


def _passes_through(project: Project, columns: set[str]) -> bool:
    """Every named column comes out of the projection as itself, unchanged."""
    if not columns:
        return True
    produced = dict(project.projections)
    for name in columns:
        expression = produced.get(name)
        if not isinstance(expression, Column) or expression.name != name:
            return False
    return True


def _merge_limits(inner: Limit, outer: Limit) -> Limit:
    offset = inner.offset + outer.offset
    counts = []
    if inner.count is not None:
        counts.append(max(inner.count - outer.offset, 0))
    if outer.count is not None:
        counts.append(outer.count)
    count = min(counts) if counts else None
    return Limit(inner.input, count, offset)
