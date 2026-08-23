"""Decide what the source runs and what we run.

Today every transformation runs in pandas, which means every run pulls the whole
table over the network into memory. That works to about five million rows and
then stops working, while the source database -- which has indexes, statistics
and thirty years of query optimisation -- sits idle.

The planner splits an IR tree in two: the longest run of operations the source
can perform for itself, compiled to one SQL query, and everything above it,
which runs here on the much smaller result.

**Two rules govern the whole thing.**

1. *Never approximate.* A node the dialect cannot express stops the prefix. It
   is not rewritten into something close; a pushed query that returns nearly the
   right answer is worse than one that refuses, because nobody notices.
2. *Always explain.* Every node that stayed local records why. The most useful
   thing an optimiser can tell somebody is what stopped it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from service_transformations.ir.expressions import supported_in
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
)
from service_transformations.ir.sql_backend import Unsupported, to_sql
from service_transformations.ir.surfaces import SourceSurface, Surface, surface_for

#: Which `supports_*` flag governs each node type.
_NODE_KIND = {
    Filter: "filter",
    Project: "project",
    Aggregate: "aggregate",
    Join: "join",
    Sort: "sort",
    Limit: "limit",
    Distinct: "distinct",
    SetOp: "set_ops",
}


@dataclass(frozen=True)
class Decision:
    """Why one node ran where it ran."""

    node: str
    pushed: bool
    reason: str

    def __str__(self) -> str:
        return f"{'pushed ' if self.pushed else 'local  '} {self.node}: {self.reason}"


@dataclass
class ExecutionPlan:
    """The split, and the reasoning behind it."""

    #: The subtree the source runs, or None when nothing could be pushed.
    pushed: Node | None
    #: The SQL for `pushed`, when the surface is a SQL database.
    sql: str | None
    #: Nodes that run here, innermost first.
    local: list[Node] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    surface: SourceSurface | None = None

    @property
    def pushed_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.pushed)

    @property
    def local_count(self) -> int:
        """How many *steps* run here. A scan is a read, not a step."""
        from service_transformations.ir.nodes import Scan as _Scan

        return sum(1 for node in self.local if not isinstance(node, _Scan))

    @property
    def fully_local(self) -> bool:
        return self.pushed_count == 0

    def explain(self) -> str:
        """A plan a person can read, for the Studio panel and for debugging."""
        lines: list[str] = []
        if self.sql:
            lines.append(f"pushed to {self.surface.name if self.surface else 'source'}:")
            lines.append(f"  {self.sql}")
        else:
            lines.append("nothing pushed down")
        if self.local:
            lines.append("ran locally:")
            for decision in self.decisions:
                if not decision.pushed:
                    lines.append(f"  {decision.node} -- {decision.reason}")
        return "\n".join(lines)


def _chain(node: Node) -> list[Node]:
    """Flatten a linear pipeline into leaf-first order.

    Returns an empty list for a tree that branches (a join or a set op), which
    the prefix walk cannot describe as a chain. Those are handled as a single
    unit: either the whole thing pushes or none of it does.
    """
    chain: list[Node] = []
    current = node
    while True:
        chain.append(current)
        children = current.children()
        if len(children) == 0:
            chain.reverse()
            return chain
        if len(children) > 1:
            return []  # branches; not a chain
        current = children[0]


def _rebuild(chain: list[Node], upto: int) -> Node:
    """Rebuild the pushed subtree from the leaf up to (and including) `upto`."""
    from dataclasses import replace

    node = chain[0]
    for index in range(1, upto + 1):
        node = replace(chain[index], input=node)  # type: ignore[arg-type]
    return node


def _can_push(node: Node, surface: SourceSurface) -> tuple[bool, str]:
    """Whether the source can run this node, and why not when it cannot."""
    if isinstance(node, Scan):
        return True, "reads the source table"

    if isinstance(node, Extension):
        return False, (
            f"{node.name!r} has no SQL form -- it is an extension step, so it "
            "always runs here"
        )

    kind = _NODE_KIND.get(type(node))
    if kind is None:
        return False, f"{type(node).__name__} is not something a source can run"

    if not surface.supports(kind):
        detail = f" ({surface.note})" if surface.note else ""
        return False, f"{surface.name} cannot run a {kind} step{detail}"

    dialect = surface.dialect
    if dialect is not None:
        for expression in _expressions_of(node):
            if not supported_in(dialect, expression):
                return False, (
                    f"{dialect} has no equivalent for part of this step, so "
                    "pushing it could change the result"
                )

    return True, f"{surface.name} runs this natively"


def _expressions_of(node: Node) -> list:
    if isinstance(node, Project):
        return [expression for _, expression in node.projections]
    if isinstance(node, Filter):
        return [node.predicate]
    if isinstance(node, Aggregate):
        return [expression for _, expression in list(node.group_by) + list(node.aggregates)]
    if isinstance(node, Sort):
        return [key.expr for key in node.keys]
    if isinstance(node, Join) and node.on is not None:
        return [node.on]
    return []


def plan(node: Node, source_type: str | None = None, *, surface: SourceSurface | None = None) -> ExecutionPlan:
    """Split the tree into what the source runs and what we run."""
    active = surface or surface_for(source_type)
    chain = _chain(node)

    if not chain:
        # Branching trees (joins, unions) are all-or-nothing for now: pushing
        # one arm and not the other means moving rows anyway, and getting the
        # boundary wrong on a join is how a cartesian product happens.
        return _plan_whole(node, active)

    if active.surface is Surface.NONE:
        return ExecutionPlan(
            pushed=None,
            sql=None,
            # The whole chain, scan included: with nothing pushed there is no
            # source result to re-root onto, so this list IS the executable
            # tree. Dropping the scan left a bare pipeline with nothing to run.
            local=chain,
            decisions=[
                Decision(str(chain[0]), False, active.note or "source cannot run steps"),
                *[Decision(str(n), False, "the source hands over rows only") for n in chain[1:]],
            ],
            surface=active,
        )

    decisions: list[Decision] = []
    boundary = -1
    for index, current in enumerate(chain):
        ok, reason = _can_push(current, active)
        if not ok:
            decisions.append(Decision(str(current), False, reason))
            break
        decisions.append(Decision(str(current), True, reason))
        boundary = index

    # Everything after the first refusal runs here, whatever it is: a step above
    # a local step cannot be pushed, because its input no longer exists there.
    for current in chain[len(decisions) :]:
        decisions.append(
            Decision(str(current), False, "runs after a step that could not be pushed")
        )

    if boundary < 0:
        return ExecutionPlan(None, None, chain, decisions, active)

    pushed = _rebuild(chain, boundary)
    sql: str | None = None
    if active.is_sql and active.dialect:
        try:
            sql = to_sql(pushed, active.dialect)
        except Unsupported as exc:
            # The compiler refused something the node-level check allowed. Fall
            # back to running everything here rather than guessing.
            return ExecutionPlan(
                pushed=None,
                sql=None,
                local=chain,
                decisions=[
                    Decision(str(chain[0]), False, f"{active.dialect} refused the query: {exc}"),
                    *[Decision(str(n), False, "runs here because nothing was pushed") for n in chain[1:]],
                ],
                surface=active,
            )

    return ExecutionPlan(pushed, sql, chain[boundary + 1 :], decisions, active)


def _plan_whole(node: Node, surface: SourceSurface) -> ExecutionPlan:
    """All-or-nothing for a branching tree."""
    if surface.surface is Surface.NONE or not surface.is_sql or not surface.dialect:
        return ExecutionPlan(
            None, None, [node],
            [Decision(str(node), False, surface.note or "source cannot run steps")],
            surface,
        )
    for current in node.walk():
        ok, reason = _can_push(current, surface)
        if not ok:
            return ExecutionPlan(
                None, None, [node],
                [Decision(str(current), False, reason)],
                surface,
            )
    try:
        sql = to_sql(node, surface.dialect)
    except Unsupported as exc:
        return ExecutionPlan(
            None, None, [node],
            [Decision(str(node), False, f"{surface.dialect} refused the query: {exc}")],
            surface,
        )
    return ExecutionPlan(
        node, sql, [],
        [Decision(str(node), True, f"{surface.name} runs the whole tree")],
        surface,
    )
