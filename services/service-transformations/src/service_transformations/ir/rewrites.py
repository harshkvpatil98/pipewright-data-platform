"""Semantics-preserving rewrites of an IR tree (Phase 22).

Phase 12 decides *where* a tree runs; this file makes small, provable changes
to the tree first so that more of it runs at the source, and less of it runs
at all. Every rewrite here is a textbook algebraic identity, and every one is
covered by the differential test: the tree before and the tree after are
executed by both backends and must agree value for value.

**What is here, and why each one is safe**

- *Predicate pushdown through a row-wise node.* ``Filter(Project(x))`` becomes
  ``Project(Filter(x))`` when every column the predicate reads passes through
  the projection unchanged. ``Filter(Sort(x))`` becomes ``Sort(Filter(x))``:
  a filter keeps the relative order of what it keeps.
- *Predicate pushdown through a join.* A conjunct that reads only one side's
  columns runs on that side before the join: either side of an inner or
  cross join, the left side of a left, semi or anti join. A conjunct reading
  both sides stays above. Never into the side an outer join pads with nulls.
- *Predicate transfer across a join's keys* (the useful form of "pull-up").
  When ``a = b`` joins the sides and a conjunct compares ``a`` with a
  constant, the same comparison on ``b`` is added to the other side: a row
  there that fails it could only have matched rows the filter removes.
  Inner, left, semi and anti joins.
- *Predicate pushdown through an aggregate* when the conjunct reads only
  grouping keys that are plain columns: removing a group's rows before
  grouping removes exactly that group.
- *Into both sides of a union* (`union_all`, `union`), columns matched by
  position; *below a distinct* when it reads only the columns that decide
  identity.
- *Limit pushdown* through a projection, and a copy into both sides of a
  `union_all` (the outer limit stays). A limit is never moved below a sort,
  a filter, a distinct, an aggregate or a join.
- *Adjacent filter and limit merges.* ``a AND b`` is true exactly when both
  were (three-valued logic); two windows of rows compose into one.
- *Constant folding,* only where every dialect agrees: whole-number ``+``,
  ``-`` and ``*`` within 64 bits, comparisons between constants of one kind,
  and ``AND``/``OR``/``NOT`` with true or false (``x AND false`` is false even
  when ``x`` is null). Decimals are not folded: the databases keep them exact
  and pandas does not. A filter on a constant true is dropped.
- *Redundant sort removal.* A sort whose keys begin with the keys of the
  sort below it makes that one pointless (both are stable). A sort below an
  aggregate with no order-sensitive measure (first, last) changes nothing:
  the groups come out ordered by key either way.
- *Projection pruning* (`prune`, after the rest): a scan reads only the
  columns something above it uses; a projection drops outputs nobody reads.
  Nothing is pruned through a union (columns match by position), a distinct
  over every column, or an extension (its needs are unknown).

**Not here.** Join reordering needs to know the sizes, so the planner that
has statistics does it (`ir/estimate.py`, `ir/federation.py`). Common
subexpressions are computed once by the pandas backend as it evaluates;
SQL databases do that themselves. Nothing looks inside an ``Extension``.

The planner applies these before it splits a tree and reports what it did,
because a rewrite that silently changed a plan would be indistinguishable
from a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shared_python.types import BOOLEAN

from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
    SortKey,
    Window,
)

_INT64 = (-(2**63), 2**63 - 1)
#: Comparisons a constant on one side makes transferable across a join key.
_TRANSFERABLE = frozenset({"eq", "ne", "lt", "le", "gt", "ge", "in_list"})
#: Measures whose answer depends on the order rows arrive in.
_ORDER_SENSITIVE = frozenset({"first", "last"})


@dataclass(frozen=True)
class Rewrite:
    """One rewrite that was applied, in words a plan panel can show."""

    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.detail}"


def rewrite(node: Node, *, prune_columns: bool = True) -> tuple[Node, list[Rewrite]]:
    """Apply every safe rewrite to a fixpoint, bottom-up, then prune columns.

    Returns the rewritten tree and what was done, in order. A tree nothing
    applies to comes back as the same object with an empty list.
    """
    applied: list[Rewrite] = []
    current = node
    for _ in range(64):  # every rule strictly shrinks or lowers something; this is a guard
        changed, current = _pass(current, applied)
        if not changed:
            break
    if prune_columns:
        pruned = prune(current, None, applied)
        if pruned is not current:
            current = pruned
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
    folded = _fold_node(node, applied)
    if folded is not None:
        return folded
    if isinstance(node, Filter):
        return _filter(node, applied)
    if isinstance(node, Limit):
        return _limit(node, applied)
    if isinstance(node, Sort) and isinstance(node.input, Sort) and _sort_covers(node.keys, node.input.keys):
        applied.append(Rewrite("drop a redundant sort", f"{node} orders by everything {node.input} did"))
        return Sort(node.input.input, node.keys)
    if isinstance(node, Aggregate) and isinstance(node.input, Sort):
        measures = {expr.name for _, expr in node.aggregates if isinstance(expr, Call)}
        if not measures & _ORDER_SENSITIVE:
            applied.append(Rewrite("drop a redundant sort", f"{node} orders its groups by key whatever comes in"))
            return replace(node, input=node.input.input)
    return None


# ---------------------------------------------------------------- filters


def _filter(node: Filter, applied: list[Rewrite]) -> Node | None:
    below = node.input
    if isinstance(below, Filter):
        applied.append(Rewrite("merge filters", f"{below.predicate} AND {node.predicate}"))
        return Filter(below.input, Call("and", (below.predicate, node.predicate)))
    if isinstance(below, Project) and _passes_through(below, node.predicate.columns_used()):
        applied.append(Rewrite("filter below projection", f"{node.predicate} now runs before {below}"))
        return Project(Filter(below.input, node.predicate), below.projections)
    if isinstance(below, Sort):
        applied.append(Rewrite("filter below sort", f"{node.predicate} now runs before {below}"))
        return Sort(Filter(below.input, node.predicate), below.keys)
    if isinstance(below, Join):
        return _filter_join(node, below, applied)
    if isinstance(below, Aggregate):
        return _filter_aggregate(node, below, applied)
    if isinstance(below, SetOp) and below.kind in ("union_all", "union"):
        mapping = dict(zip(below.left.schema(), below.right.schema(), strict=True))
        applied.append(Rewrite("filter into both sides of a union", f"{node.predicate} now runs on each side"))
        return SetOp(Filter(below.left, node.predicate),
                     Filter(below.right, _renamed(node.predicate, mapping)), below.kind)
    if isinstance(below, Distinct):
        used = node.predicate.columns_used()
        if not below.subset or used <= set(below.subset):
            applied.append(Rewrite("filter below distinct", f"{node.predicate} reads only what decides identity"))
            return Distinct(Filter(below.input, node.predicate), below.subset, below.keep)
    if isinstance(below, Window) and below.partition_by:
        # A filter on the partition columns keeps or drops whole partitions, so
        # every row it keeps sees exactly the rows it saw before. Anything else
        # would change which rows a rank or a total counts.
        if node.predicate.columns_used() <= set(below.partition_by):
            applied.append(Rewrite("filter below window", f"{node.predicate} keeps whole partitions, so it runs first"))
            return replace(below, input=Filter(below.input, node.predicate))
    return None


def _conjuncts(expr: Expr) -> list[Expr]:
    if isinstance(expr, Call) and expr.name == "and":
        return [part for arg in expr.args for part in _conjuncts(arg)]
    return [expr]


def _and(parts: list[Expr]) -> Expr:
    out = parts[0]
    for part in parts[1:]:
        out = Call("and", (out, part))
    return out


def _sides(join: Join) -> dict[str, tuple[str, str]]:
    """Each output column of the join: which side it comes from, and its name there."""
    left = join.left.schema()
    right = join.right.schema()
    if join.how in ("semi", "anti"):
        return {name: ("left", name) for name in left}
    overlap = left.keys() & right.keys()
    out: dict[str, tuple[str, str]] = {}
    for name in left:
        out[f"{name}{join.left_suffix}" if name in overlap else name] = ("left", name)
    for name in right:
        out[f"{name}{join.right_suffix}" if name in overlap else name] = ("right", name)
    return out


def _equi_pairs(on: Expr | None) -> list[tuple[str, str]]:
    if on is None:
        return []
    if isinstance(on, Call) and on.name == "and":
        return [pair for arg in on.args for pair in _equi_pairs(arg)]
    if isinstance(on, Call) and on.name == "eq" and all(isinstance(a, Column) for a in on.args):
        return [(on.args[0].name, on.args[1].name)]  # type: ignore[union-attr]
    return []


def _filter_join(node: Filter, join: Join, applied: list[Rewrite]) -> Node | None:
    sides = _sides(join)
    left_ok = join.how in ("inner", "cross", "left", "semi", "anti")
    right_ok = join.how in ("inner", "cross", "right")
    to_left: list[Expr] = []
    to_right: list[Expr] = []
    copied: list[Expr] = []
    stay: list[Expr] = []
    left_to_right = dict(_equi_pairs(join.on))
    for part in _conjuncts(node.predicate):
        used = part.columns_used()
        where = {sides.get(name, ("?", name))[0] for name in used}
        if used and where == {"left"} and left_ok:
            local = _renamed(part, {name: sides[name][1] for name in used})
            to_left.append(local)
            transferred = _transfer(local, left_to_right)
            if transferred is not None and join.how in ("inner", "left", "semi", "anti"):
                copied.append(transferred)
        elif used and where == {"right"} and right_ok:
            to_right.append(_renamed(part, {name: sides[name][1] for name in used}))
        else:
            stay.append(part)
    if not to_left and not to_right:
        return None
    for part in to_left:
        applied.append(Rewrite("filter below join", f"{part} now runs on the left input of {join}"))
    for part in to_right:
        applied.append(Rewrite("filter below join", f"{part} now runs on the right input of {join}"))
    for part in copied:
        applied.append(Rewrite("filter copied across a join", f"{part} holds on the right input too, through the join's keys"))
    right_parts = to_right + copied
    left = Filter(join.left, _and(to_left)) if to_left else join.left
    right = Filter(join.right, _and(right_parts)) if right_parts else join.right
    lowered = replace(join, left=left, right=right)
    return Filter(lowered, _and(stay)) if stay else lowered


def _transfer(part: Expr, left_to_right: dict[str, str]) -> Expr | None:
    """`a > 5` as `b > 5`, when `a = b` joins the sides and the other operands are constants."""
    if not isinstance(part, Call) or part.name not in _TRANSFERABLE:
        return None
    columns = [arg for arg in part.args if isinstance(arg, Column)]
    others = [arg for arg in part.args if not isinstance(arg, Column)]
    if len(columns) != 1 or columns[0].name not in left_to_right or not all(isinstance(o, Literal) for o in others):
        return None
    return _renamed(part, {columns[0].name: left_to_right[columns[0].name]})


def _filter_aggregate(node: Filter, aggregate: Aggregate, applied: list[Rewrite]) -> Node | None:
    if not aggregate.group_by:
        return None
    keys = {name: expr.name for name, expr in aggregate.group_by if isinstance(expr, Column)}
    down: list[Expr] = []
    stay: list[Expr] = []
    for part in _conjuncts(node.predicate):
        used = part.columns_used()
        if used and used <= keys.keys():
            down.append(_renamed(part, {name: keys[name] for name in used}))
        else:
            stay.append(part)
    if not down:
        return None
    for part in down:
        applied.append(Rewrite("filter below aggregate", f"{part} reads only grouping keys"))
    lowered = replace(aggregate, input=Filter(aggregate.input, _and(down)))
    return Filter(lowered, _and(stay)) if stay else lowered


def _renamed(expr: Expr, names: dict[str, str]) -> Expr:
    """The expression with its columns renamed (the same tree when nothing changes)."""
    if not names or all(old == new for old, new in names.items()):
        return expr
    if isinstance(expr, Column):
        return Column(names.get(expr.name, expr.name))
    if isinstance(expr, Literal):
        return expr
    if isinstance(expr, Cast):
        return Cast(_renamed(expr.value, names), expr.to)
    if isinstance(expr, Case):
        return Case(tuple((_renamed(c, names), _renamed(v, names)) for c, v in expr.branches),
                    _renamed(expr.default, names) if expr.default is not None else None)
    if isinstance(expr, Call):
        return Call(expr.name, tuple(_renamed(arg, names) for arg in expr.args))
    return expr  # pragma: no cover - every expression kind is above


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


# ----------------------------------------------------------------- limits


def _limit(node: Limit, applied: list[Rewrite]) -> Node | None:
    below = node.input
    if isinstance(below, Limit):
        merged = _merge_limits(below, node)
        applied.append(Rewrite("merge limits", f"{below} then {node} is {merged}"))
        return merged
    if isinstance(below, Project):
        applied.append(Rewrite("limit below projection", f"{node} now runs before {below}"))
        return Project(Limit(below.input, node.count, node.offset), below.projections)
    if isinstance(below, SetOp) and below.kind == "union_all" and node.count is not None:
        enough = node.count + node.offset
        sides = [below.left, below.right]
        if all(isinstance(side, Limit) and side.offset == 0 and side.count is not None and side.count <= enough
               for side in sides):
            return None
        capped = [side if isinstance(side, Limit) and side.offset == 0 and side.count is not None
                  and side.count <= enough else Limit(side, enough) for side in sides]
        applied.append(Rewrite("limit into both sides of a union", f"each side needs at most {enough} rows"))
        return Limit(SetOp(capped[0], capped[1], below.kind), node.count, node.offset)
    return None


def _merge_limits(inner: Limit, outer: Limit) -> Limit:
    offset = inner.offset + outer.offset
    counts = []
    if inner.count is not None:
        counts.append(max(inner.count - outer.offset, 0))
    if outer.count is not None:
        counts.append(outer.count)
    count = min(counts) if counts else None
    return Limit(inner.input, count, offset)


# ------------------------------------------------------------------ sorts


def _sort_covers(outer: tuple[SortKey, ...], inner: tuple[SortKey, ...]) -> bool:
    """The outer sort's keys begin with the inner's, the same way round, nulls in the same place."""
    if len(inner) > len(outer):
        return False
    if outer[0].nulls_first != inner[0].nulls_first:
        return False
    return all(o.expr == i.expr and o.direction == i.direction for o, i in zip(outer, inner, strict=False))


# --------------------------------------------------------------- constants


def _fold_node(node: Node, applied: list[Rewrite]) -> Node | None:
    """Fold the constants in a node's expressions; drop a filter on a constant true."""
    if isinstance(node, Filter):
        folded = fold(node.predicate)
        if isinstance(folded, Literal) and folded.value is True:
            applied.append(Rewrite("drop a filter that keeps every row", f"{node.predicate} is always true"))
            return node.input
        if folded != node.predicate:
            applied.append(Rewrite("fold constants", f"{node.predicate} is {folded}"))
            return Filter(node.input, folded)
        return None
    if isinstance(node, Project):
        projections = tuple((name, fold(expr)) for name, expr in node.projections)
        if projections != node.projections:
            changed = [f"{name} = {expr}" for (name, expr), (_, old) in zip(projections, node.projections, strict=True)
                       if expr != old]
            applied.append(Rewrite("fold constants", ", ".join(changed)))
            return Project(node.input, projections)
    return None


def fold(expr: Expr) -> Expr:
    """The expression with every constant part worked out, where it is safe to."""
    if isinstance(expr, (Column, Literal)):
        return expr
    if isinstance(expr, Cast):
        return Cast(fold(expr.value), expr.to)
    if isinstance(expr, Case):
        return Case(tuple((fold(c), fold(v)) for c, v in expr.branches),
                    fold(expr.default) if expr.default is not None else None)
    if not isinstance(expr, Call):
        return expr
    args = tuple(fold(arg) for arg in expr.args)
    call = Call(expr.name, args) if args != expr.args else expr
    name = call.name
    if name in ("and", "or"):
        return _fold_logic(call)
    if name == "not" and isinstance(args[0], Literal) and isinstance(args[0].value, bool):
        return Literal(not args[0].value, BOOLEAN)
    if name == "not" and isinstance(args[0], Call) and args[0].name == "not":
        return args[0].args[0]
    if name in ("add", "sub", "mul") and all(_whole(arg) for arg in args):
        a, b = args[0].value, args[1].value  # type: ignore[union-attr]
        value = a + b if name == "add" else a - b if name == "sub" else a * b
        if _INT64[0] <= value <= _INT64[1]:
            return Literal(value, call.type_of({}))
        return call
    if name in ("eq", "ne", "lt", "le", "gt", "ge") and all(isinstance(arg, Literal) for arg in args):
        a, b = args[0].value, args[1].value  # type: ignore[union-attr]
        if a is None or b is None or type(a) is not type(b) or isinstance(a, float):
            return call  # null, mixed kinds and decimals compare by each dialect's rules
        return Literal(_COMPARE[name](a, b), BOOLEAN)
    return call


_COMPARE: dict[str, Any] = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b, "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
}


def _whole(expr: Expr) -> bool:
    return isinstance(expr, Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool)


def _fold_logic(call: Call) -> Expr:
    """Three-valued AND/OR with a constant true or false on either side."""
    a, b = call.args
    absorbing, identity = (False, True) if call.name == "and" else (True, False)
    for this, other in ((a, b), (b, a)):
        if isinstance(this, Literal) and isinstance(this.value, bool):
            if this.value is absorbing:
                return Literal(absorbing, BOOLEAN)
            if this.value is identity:
                return other
    return call


# ----------------------------------------------------------------- pruning


def prune(node: Node, needed: set[str] | None, applied: list[Rewrite]) -> Node:
    """Read and compute only the columns something above uses.

    `needed` is the set of this node's output columns used above, or None for
    "all of them" (the tree's own output, and anything whose needs are unknown).
    """
    if isinstance(node, Scan):
        if needed is None:
            return node
        kept = tuple((name, type_) for name, type_ in node.columns if name in needed) or node.columns[:1]
        if len(kept) == len(node.columns):
            return node
        applied.append(Rewrite("read only the columns used",
                               f"{node} reads {len(kept)} of its {len(node.columns)} columns"))
        return replace(node, columns=kept)
    if isinstance(node, Project):
        projections = node.projections if needed is None else (
            tuple((n, e) for n, e in node.projections if n in needed) or node.projections[:1])
        if len(projections) < len(node.projections):
            kept_names = {name for name, _ in projections}
            dropped = [name for name, _ in node.projections if name not in kept_names]
            applied.append(Rewrite("drop columns nobody reads", f"{node} no longer computes {', '.join(dropped)}"))
        used: set[str] = set()
        for _, expr in projections:
            used |= expr.columns_used()
        child = prune(node.input, used, applied)
        if child is node.input and projections == node.projections:
            return node
        return Project(child, projections)
    if isinstance(node, Filter):
        return _same_or(node, prune(node.input, None if needed is None else needed | node.predicate.columns_used(), applied))
    if isinstance(node, Sort):
        child_needed = None
        if needed is not None:
            child_needed = set(needed)
            for key in node.keys:
                child_needed |= key.expr.columns_used()
        return _same_or(node, prune(node.input, child_needed, applied))
    if isinstance(node, Limit):
        return _same_or(node, prune(node.input, needed, applied))
    if isinstance(node, Distinct):
        child_needed = None if needed is None or not node.subset else needed | set(node.subset)
        return _same_or(node, prune(node.input, child_needed, applied))
    if isinstance(node, Aggregate):
        used = set()
        for _, expr in (*node.group_by, *node.aggregates):
            used |= expr.columns_used()
        return _same_or(node, prune(node.input, used, applied))
    if isinstance(node, Window):
        functions = node.functions if needed is None else tuple(
            (name, call) for name, call in node.functions if name in needed)
        if not functions:
            # Nothing above reads what the window computes, and it changes no
            # row: it goes, and so does the work of ordering every partition.
            applied.append(Rewrite("drop columns nobody reads", f"{node} is not read above"))
            return prune(node.input, needed, applied)
        if len(functions) < len(node.functions):
            dropped = [name for name, _ in node.functions if name not in dict(functions)]
            applied.append(Rewrite("drop columns nobody reads", f"{node} no longer computes {', '.join(dropped)}"))
        child_needed = None
        if needed is not None:
            child_needed = (set(needed) - {name for name, _ in node.functions}) | set(node.partition_by)
            for key in node.order_by:
                child_needed |= key.expr.columns_used()
            for _, call in functions:
                child_needed |= call.columns_used()
        child = prune(node.input, child_needed, applied)
        if child is node.input and functions == node.functions:
            return node
        return replace(node, input=child, functions=functions)
    if isinstance(node, Join):
        sides = _sides(node)
        pairs = _equi_pairs(node.on)
        if needed is None or (node.on is not None and not pairs):
            # The tree's own output, or a condition of another shape: keep everything.
            left_needed: set[str] | None = None
            right_needed: set[str] | None = None
        else:
            left_needed = {sides[name][1] for name in needed if sides.get(name, ("?",))[0] == "left"}
            right_needed = {sides[name][1] for name in needed if sides.get(name, ("?",))[0] == "right"}
            for left_key, right_key in pairs:
                left_needed.add(left_key)
                right_needed.add(right_key)
            # A name both sides have is suffixed on the way out; keep it on both
            # sides while either needs it, or dropping it from one would rename
            # the other's ("id_right" back to "id") under whatever reads it.
            if node.how not in ("semi", "anti"):
                for name in node.left.schema().keys() & node.right.schema().keys():
                    if name in left_needed or name in right_needed:
                        left_needed.add(name)
                        right_needed.add(name)
        left = prune(node.left, left_needed, applied)
        right = prune(node.right, right_needed, applied)
        if left is node.left and right is node.right:
            return node
        return replace(node, left=left, right=right)
    # A union matches columns by position and an extension's needs are unknown:
    # everything below them is kept.
    children = node.children()
    if not children:
        return node
    pruned = [prune(child, None, applied) for child in children]
    if all(new is old for new, old in zip(pruned, children, strict=True)):
        return node
    return _with_children(node, pruned)


def _same_or(node: Node, child: Node) -> Node:
    """The node itself when its input did not change, else the node over the new input."""
    return node if child is node.input else replace(node, input=child)  # type: ignore[attr-defined]
