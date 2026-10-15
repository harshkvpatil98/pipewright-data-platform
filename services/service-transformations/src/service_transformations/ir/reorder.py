"""Inner joins in the order that keeps what is in between smallest (D2, O3).

`A JOIN B JOIN C` gives the same rows in any order, but not the same work:
joining the two tables that match least first can leave thousands of rows
in between where the written order leaves millions. From the estimates
(`ir/estimate.py`), this starts with the smallest table and adds, each time,
the table whose join with what is built so far is estimated smallest, among
those a condition connects to it.

Only a group of inner joins on equal columns is reordered, and only when no
two of its tables share a column name (a shared name would be renamed
differently in another order); anything else is left as written. The result
is put back in the written column order, so nothing above can tell. Proven by
the differential test: written order and chosen order, same rows.
"""

from __future__ import annotations

from collections.abc import Mapping

from shared_python.statistics import TableStats

from service_transformations.ir.estimate import estimate
from service_transformations.ir.expressions import Call, Column, Expr
from service_transformations.ir.nodes import Aggregate, Distinct, Filter, Join, Limit, Node, Project, SetOp, Sort, Window
from service_transformations.ir.rewrites import Rewrite


def reorder_joins(node: Node, stats: Mapping[str, TableStats | None]) -> tuple[Node, list[Rewrite]]:
    applied: list[Rewrite] = []
    return _walk(node, stats, applied), applied


def _walk(node: Node, stats: Mapping[str, TableStats | None], applied: list[Rewrite]) -> Node:
    if isinstance(node, Join) and node.how == "inner":
        group = _group(node)
        if group is not None:
            relations, conditions = group
            relations = [_walk(relation, stats, applied) for relation in relations]
            chosen = _greedy(relations, conditions, stats)
            if chosen is not None:
                tree, written_cost, chosen_cost, order = chosen
                if chosen_cost < written_cost:
                    applied.append(Rewrite(
                        "join order by cost",
                        f"joined {' then '.join(order)}: about {chosen_cost:,.0f} rows in between, "
                        f"not {written_cost:,.0f} as written",
                    ))
                    return Project(tree, tuple((name, Column(name)) for name in node.schema()))
            return _rebuild_as_written(node, stats, applied)
    return _map_children(node, lambda child: _walk(child, stats, applied))


def _rebuild_as_written(node: Join, stats, applied) -> Node:
    return Join(_walk(node.left, stats, applied), _walk(node.right, stats, applied), on=node.on, how=node.how,
                left_suffix=node.left_suffix, right_suffix=node.right_suffix)


def _map_children(node: Node, fn) -> Node:
    if isinstance(node, Project):
        return Project(fn(node.input), node.projections)
    if isinstance(node, Filter):
        return Filter(fn(node.input), node.predicate)
    if isinstance(node, Aggregate):
        return Aggregate(fn(node.input), group_by=node.group_by, aggregates=node.aggregates)
    if isinstance(node, Sort):
        return Sort(fn(node.input), node.keys)
    if isinstance(node, Limit):
        return Limit(fn(node.input), count=node.count, offset=node.offset)
    if isinstance(node, Distinct):
        return Distinct(fn(node.input), subset=node.subset, keep=node.keep)
    if isinstance(node, Join):
        return Join(fn(node.left), fn(node.right), on=node.on, how=node.how,
                    left_suffix=node.left_suffix, right_suffix=node.right_suffix)
    if isinstance(node, SetOp):
        return SetOp(fn(node.left), fn(node.right), kind=node.kind)
    if isinstance(node, Window):
        return Window(fn(node.input), node.partition_by, node.order_by, node.functions)
    return node  # a Scan, or an Extension, which this does not look inside


def _conjuncts(expr: Expr | None) -> list[Expr]:
    if isinstance(expr, Call) and expr.name == "and":
        return [part for arg in expr.args for part in _conjuncts(arg)]
    return [] if expr is None else [expr]


def _group(node: Join) -> tuple[list[Node], list[tuple[str, str]]] | None:
    """The tables of a run of inner joins and their equal-column conditions, or None."""
    relations: list[Node] = []
    pairs: list[tuple[str, str]] = []

    def collect(current: Node) -> bool:
        if isinstance(current, Join) and current.how == "inner":
            for part in _conjuncts(current.on):
                if not (isinstance(part, Call) and part.name == "eq"
                        and all(isinstance(arg, Column) for arg in part.args)):
                    return False
                pairs.append((part.args[0].name, part.args[1].name))  # type: ignore[union-attr]
            return collect(current.left) and collect(current.right)
        relations.append(current)
        return True

    if not collect(node) or len(relations) < 3:
        return None
    names = [name for relation in relations for name in relation.schema()]
    if len(names) != len(set(names)):
        return None
    return relations, pairs


def _owner(relations: list[Node]) -> dict[str, int]:
    return {name: index for index, relation in enumerate(relations) for name in relation.schema()}


def _join(left: Node, right: Node, pairs: list[tuple[str, str]]) -> Join:
    """Join on `pairs`, each turned so its first column is the left side's."""
    left_columns = set(left.schema())
    conditions = [Call("eq", (Column(a), Column(b))) if a in left_columns else Call("eq", (Column(b), Column(a)))
                  for a, b in pairs]
    on = conditions[0] if len(conditions) == 1 else Call("and", tuple(conditions))
    return Join(left, right, on=on, how="inner")


def _greedy(relations: list[Node], pairs: list[tuple[str, str]], stats) -> tuple[Node, float, float, list[str]] | None:
    owner = _owner(relations)
    if any(a not in owner or b not in owner for a, b in pairs):
        return None
    sizes = [estimate(relation, stats).rows for relation in relations]
    # What the written order costs: the rows of every join in between.
    written_cost = _cost_as_written(relations, pairs, stats)

    start = min(range(len(relations)), key=lambda index: sizes[index])
    built: Node = relations[start]
    inside = {start}
    remaining = list(pairs)
    cost = 0.0
    order = [_label(relations[start])]
    while len(inside) < len(relations):
        best = None
        for index in range(len(relations)):
            if index in inside:
                continue
            linking = [(a, b) for a, b in remaining
                       if {owner[a], owner[b]} <= inside | {index} and index in (owner[a], owner[b])]
            if not linking:
                continue
            candidate = _join(built, relations[index], linking)
            rows = estimate(candidate, stats).rows
            if best is None or rows < best[0]:
                best = (rows, index, candidate, linking)
        if best is None:
            return None  # a table no condition reaches: a cross join, left as written
        rows, index, built, linking = best
        inside.add(index)
        remaining = [pair for pair in remaining if pair not in linking]
        order.append(_label(relations[index]))
        if len(inside) < len(relations):
            cost += rows
    if remaining:
        # Conditions between tables already joined (a cycle): checked last, as a filter would be.
        built = Filter(built, _and([Call("eq", (Column(a), Column(b))) for a, b in remaining]))
    return built, written_cost, cost, order


def _cost_as_written(relations: list[Node], pairs: list[tuple[str, str]], stats) -> float:
    """Rows in between when joined left to right as listed (the written order is left-deep)."""
    owner = _owner(relations)
    built, inside, cost = relations[0], {0}, 0.0
    remaining = list(pairs)
    for index in range(1, len(relations)):
        linking = [(a, b) for a, b in remaining if {owner[a], owner[b]} <= inside | {index}]
        if not linking:
            return float("inf")
        built = _join(built, relations[index], linking)
        remaining = [pair for pair in remaining if pair not in linking]
        inside.add(index)
        if index < len(relations) - 1:
            cost += estimate(built, stats).rows
    return cost


def _and(parts: list[Expr]) -> Expr:
    return parts[0] if len(parts) == 1 else Call("and", tuple(parts))


def _label(node: Node) -> str:
    from service_transformations.ir.nodes import Scan

    for part in node.walk():
        if isinstance(part, Scan):
            return str(part)[5:-1]
    return type(node).__name__
