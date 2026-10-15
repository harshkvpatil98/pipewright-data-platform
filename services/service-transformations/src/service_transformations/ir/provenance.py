"""Which input columns each output column of a tree is made from.

Lineage for a tool is read off the tool's IR. A tool that is one projection
needs nothing more than the projection's expressions, but a tool that builds a
window and then computes over it (a percent change is a lag and a division)
names a temporary column the input never had. This walks the tree and says,
for every column a node produces, which columns of the leaves it comes from,
and whether it is one of them passed through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from service_transformations.ir.expressions import Column, Expr
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
    Window,
)


@dataclass(frozen=True)
class Origin:
    #: Leaf columns this column is made from.
    sources: frozenset[str]
    #: True when it is one leaf column, unchanged.
    unchanged: bool


Origins = dict[str, Origin]


def provenance(node: Node) -> Origins:
    if isinstance(node, Scan):
        return {name: Origin(frozenset({name}), True) for name, _ in node.columns}
    if isinstance(node, Project):
        below = provenance(node.input)
        return {name: _of(expr, below) for name, expr in node.projections}
    if isinstance(node, (Filter, Sort, Limit, Distinct)):
        return provenance(node.input)
    if isinstance(node, Window):
        below = provenance(node.input)
        out = dict(below)
        ordering: set[str] = set()
        for key in node.order_by:
            ordering |= key.expr.columns_used()
        for name, call in node.functions:
            used = call.columns_used() or ordering
            out[name] = Origin(_sources(used, below), False)
        return out
    if isinstance(node, Aggregate):
        below = provenance(node.input)
        out = {name: _of(expr, below) for name, expr in node.group_by}
        out.update({name: Origin(_of(expr, below).sources, False) for name, expr in node.aggregates})
        return out
    if isinstance(node, Join):
        left, right = provenance(node.left), provenance(node.right)
        if node.how in ("semi", "anti"):
            return left
        overlap = node.left.schema().keys() & node.right.schema().keys()
        out = {f"{name}{node.left_suffix}" if name in overlap else name: origin for name, origin in left.items()}
        out.update({f"{name}{node.right_suffix}" if name in overlap else name: origin
                    for name, origin in right.items()})
        return out
    if isinstance(node, SetOp):
        left, right = provenance(node.left), provenance(node.right)
        return {name: Origin(left[name].sources | right[other].sources, left[name].unchanged)
                for name, other in zip(left, right)}
    if isinstance(node, Extension):
        below = provenance(node.input)
        config = node.config_dict()
        named = _named_in(config, set(node.input.schema()))
        # A tool that writes a column says so in "into"; that column is new, or
        # is the one it read, changed.
        into = config.get("into")
        written = {into} if isinstance(into, str) else set(into) if isinstance(into, (list, tuple)) else set()
        out: Origins = {}
        for name in node.schema():
            if name in below and name not in written and (node.output_schema is None or name in node.input.schema()):
                out[name] = below[name]
            else:
                out[name] = Origin(_sources(named, below), False)
        return out
    return {name: Origin(frozenset(), False) for name in node.schema()}


def columns_read(node: Node) -> frozenset[str]:
    """Leaf columns a tree reads to decide which rows, or their order, without producing them."""
    read: set[str] = set()
    for part in node.walk():
        children = part.children()
        if not children:
            continue
        below = provenance(children[0])
        used: set[str] = set()
        if isinstance(part, Filter):
            used = part.predicate.columns_used()
        elif isinstance(part, Sort):
            used = {name for key in part.keys for name in key.expr.columns_used()}
        elif isinstance(part, Window):
            used = set(part.partition_by) | {name for key in part.order_by for name in key.expr.columns_used()}
        elif isinstance(part, Distinct):
            used = set(part.subset)
        read |= _sources(used, below)
    return frozenset(read)


def _of(expr: Expr, below: Origins) -> Origin:
    if isinstance(expr, Column) and expr.name in below:
        return below[expr.name]
    return Origin(_sources(expr.columns_used(), below), False)


def _sources(names, below: Origins) -> frozenset[str]:
    found: set[str] = set()
    for name in names:
        if name in below:
            found |= below[name].sources
    return frozenset(found)


def _named_in(config: dict, columns: set[str]) -> set[str]:
    """Input columns an extension's settings name, which is what it reads."""
    found: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, str) and value in columns:
            found.add(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(config)
    return found
