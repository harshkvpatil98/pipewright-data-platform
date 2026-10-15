"""How many rows each node of a tree will produce, from statistics (D2, O2).

Phase 12 decides where a tree runs. To decide *how* -- which join first,
which side of a query across sources to move, whether to ship a filter as an
`IN` list -- the planner needs to know how big things are. This estimates
every node's rows and width from `shared_python.statistics.TableStats` and
says how it got each number, because an estimate that cannot explain itself
is indistinguishable from a made-up one:

- *equality* from the commonest values when the constant is one of them, else
  the rest spread evenly over the other distinct values;
- *ranges* from the equal-count histogram (whole buckets, and a straight line
  through the bucket the constant falls in), else from the lowest and highest
  value;
- *empty* from the share of empty values; `AND` multiplies, `OR` adds less the
  overlap (columns are assumed independent, the textbook simplification);
- *joins* on equal keys from `|L| x |R| / max(distinct keys)`; *groups* from
  the product of the grouping keys' distinct values, never more than the rows;
- anything else -- a pattern, a function, an extension, a table with no
  statistics -- is a stated guess (`guessed=True`), never presented as known.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from shared_python.statistics import ColumnStats, TableStats
from shared_python.types import Kind

from service_transformations.ir.expressions import Call, Cast, Column, Expr, Literal
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

#: Rows assumed for a table with no statistics at all.
UNKNOWN_ROWS = 1_000
#: What a predicate keeps when nothing says better.
GUESS_SELECTIVITY = 0.25
GUESS_RANGE = 1 / 3
_TEMPORAL = {Kind.DATE, Kind.TIMESTAMP}
_NUMERIC = {Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64, Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64,
            Kind.FLOAT32, Kind.FLOAT64, Kind.DECIMAL}
#: Bytes a value takes, by kind, for estimating what moves over the network.
_WIDTH = {Kind.STRING: 32, Kind.JSON: 64, Kind.BYTES: 64}


@dataclass(frozen=True)
class NodeEstimate:
    node: str
    rows: float
    #: How the number was got, in words.
    how: str
    guessed: bool = False


@dataclass
class _Shape:
    """A node's output as the estimator sees it."""

    rows: float
    columns: dict[str, ColumnStats] = field(default_factory=dict)
    guessed: bool = False


@dataclass
class Estimate:
    rows: float
    width: int
    steps: list[NodeEstimate]

    @property
    def guessed(self) -> bool:
        return any(step.guessed for step in self.steps)

    @property
    def bytes(self) -> float:
        return self.rows * self.width


def scan_key(scan: Scan) -> str:
    """How a scan's statistics are looked up: by its name alone, or, for a tree
    that reads from several sources, by where it lives too."""
    if scan.origin is None and scan.schema_name is None:
        return scan.source
    return f"{scan.origin or ''}|{scan.schema_name or ''}|{scan.source}"


def estimate(node: Node, stats: Mapping[str, TableStats | None]) -> Estimate:
    """Rows and width of `node`'s output, with every node's estimate and why."""
    steps: list[NodeEstimate] = []
    shape = _walk(node, stats, steps)
    return Estimate(rows=shape.rows, width=width_of(node), steps=steps)


def width_of(node: Node) -> int:
    return sum(_WIDTH.get(type_.kind, 8) for type_ in node.schema().values()) or 8


def _walk(node: Node, stats: Mapping[str, TableStats | None], steps: list[NodeEstimate]) -> _Shape:
    if isinstance(node, Scan):
        table = stats.get(scan_key(node))
        if table is None:
            shape = _Shape(UNKNOWN_ROWS, {}, guessed=True)
            steps.append(NodeEstimate(str(node), UNKNOWN_ROWS, "a guess: there are no statistics for it", True))
            return shape
        shape = _Shape(float(table.rows), {name: table.columns[name] for name, _ in node.columns if name in table.columns})
        steps.append(NodeEstimate(str(node), float(table.rows), f"{table.rows:,} rows, from {table.method}"))
        return shape

    if isinstance(node, Project):
        below = _walk(node.input, stats, steps)
        columns = {}
        for name, expr in node.projections:
            if isinstance(expr, Column) and expr.name in below.columns:
                columns[name] = replace(below.columns[expr.name], name=name)
            elif isinstance(expr, Cast) and isinstance(expr.value, Column) and expr.value.name in below.columns:
                # Parsing dates (or numbers) written as text keeps what is known of them.
                known = below.columns[expr.value.name]
                if (expr.to.kind in _TEMPORAL and known.kind == "datetime") or \
                        (expr.to.kind in _NUMERIC and known.kind == "number"):
                    columns[name] = replace(known, name=name)
        shape = _Shape(below.rows, columns, below.guessed)
        steps.append(NodeEstimate(str(node), below.rows, "the rows it is given", below.guessed))
        return shape

    if isinstance(node, Filter):
        below = _walk(node.input, stats, steps)
        share, how, guessed = _selectivity(node.predicate, below)
        rows = below.rows * share
        shape = _Shape(rows, _capped(below.columns, rows), below.guessed or guessed)
        steps.append(NodeEstimate(str(node), rows, how, shape.guessed))
        return shape

    if isinstance(node, Sort):
        below = _walk(node.input, stats, steps)
        steps.append(NodeEstimate(str(node), below.rows, "the rows it is given", below.guessed))
        return below

    if isinstance(node, Limit):
        below = _walk(node.input, stats, steps)
        rows = max(0.0, below.rows - node.offset)
        if node.count is not None:
            rows = min(rows, float(node.count))
        steps.append(NodeEstimate(str(node), rows, "at most its limit", below.guessed))
        return _Shape(rows, _capped(below.columns, rows), below.guessed)

    if isinstance(node, Distinct):
        below = _walk(node.input, stats, steps)
        keys = list(node.subset) or list(node.input.schema())
        rows, known = _distinct_product(keys, below)
        how = "distinct combinations of " + ", ".join(keys) if known else "a guess: every row distinct"
        steps.append(NodeEstimate(str(node), rows, how, below.guessed or not known))
        return _Shape(rows, _capped(below.columns, rows), below.guessed or not known)

    if isinstance(node, Aggregate):
        below = _walk(node.input, stats, steps)
        if not node.group_by:
            steps.append(NodeEstimate(str(node), 1.0, "one row: there are no groups"))
            return _Shape(1.0, {})
        keys = [expr.name if isinstance(expr, Column) else name for name, expr in node.group_by]
        rows, known = _distinct_product(keys, below)
        if not known:
            rows = max(1.0, math.sqrt(below.rows))
        columns = {name: replace(below.columns[expr.name], name=name) for name, expr in node.group_by
                   if isinstance(expr, Column) and expr.name in below.columns}
        how = f"one row per group of {', '.join(name for name, _ in node.group_by)}" if known \
            else "a guess: the square root of the rows, one row per group"
        steps.append(NodeEstimate(str(node), rows, how, below.guessed or not known))
        return _Shape(rows, _capped(columns, rows), below.guessed or not known)

    if isinstance(node, Join):
        return _join(node, stats, steps)

    if isinstance(node, SetOp):
        left = _walk(node.left, stats, steps)
        right = _walk(node.right, stats, steps)
        rows = {"union_all": left.rows + right.rows, "union": left.rows + right.rows,
                "intersect": min(left.rows, right.rows), "except": left.rows}[node.kind]
        steps.append(NodeEstimate(str(node), rows, f"{node.kind.replace('_', ' ')} of both sides",
                                  left.guessed or right.guessed or node.kind != "union_all"))
        return _Shape(rows, {}, left.guessed or right.guessed)

    if isinstance(node, Extension):
        below = _walk(node.input, stats, steps)
        steps.append(NodeEstimate(str(node), below.rows, "a guess: what this step does to the rows is not known", True))
        return _Shape(below.rows, {}, True)

    raise ValueError(f"Cannot estimate {type(node).__name__}.")  # pragma: no cover


def _capped(columns: dict[str, ColumnStats], rows: float) -> dict[str, ColumnStats]:
    """Fewer rows cannot hold more distinct values than rows."""
    return {name: replace(column, distinct=None if column.distinct is None else max(1, min(column.distinct, int(rows) or 1)))
            for name, column in columns.items()}


def _distinct_product(keys: list[str], shape: _Shape) -> tuple[float, bool]:
    product = 1.0
    for key in keys:
        column = shape.columns.get(key)
        if column is None or not column.distinct:
            return shape.rows, False
        product *= column.distinct + (1 if column.empty_share > 0 else 0)
    return min(product, shape.rows), True


def _join(node: Join, stats: Mapping[str, TableStats | None], steps: list[NodeEstimate]) -> _Shape:
    left = _walk(node.left, stats, steps)
    right = _walk(node.right, stats, steps)
    guessed = left.guessed or right.guessed
    if node.how == "cross":
        rows = left.rows * right.rows
        steps.append(NodeEstimate(str(node), rows, "every left row with every right row", guessed))
        return _Shape(rows, {}, guessed)
    pairs = _pairs(node.on)
    if pairs:
        distinct = []
        for left_key, right_key in pairs:
            a, b = left.columns.get(left_key), right.columns.get(right_key)
            distinct.append(max(a.distinct if a and a.distinct else 0, b.distinct if b and b.distinct else 0))
        known = all(distinct)
        matched = left.rows * right.rows / max(math.prod(distinct), 1) if known else max(left.rows, right.rows)
        how = (f"{left.rows:,.0f} × {right.rows:,.0f} rows over {math.prod(distinct):,} distinct keys" if known
               else "a guess: as many rows as the larger side")
    else:
        known = False
        matched = left.rows * right.rows * GUESS_SELECTIVITY
        how = "a guess: a quarter of every pairing, for a condition of that shape"
    guessed = guessed or not known
    if node.how == "semi":
        rows = min(left.rows, matched)
        how = "the left rows that find a match"
    elif node.how == "anti":
        rows = max(0.0, left.rows - min(left.rows, matched))
        how = "the left rows that find no match"
    elif node.how == "left":
        rows = max(left.rows, matched)
    elif node.how == "right":
        rows = max(right.rows, matched)
    elif node.how == "full":
        rows = max(left.rows + right.rows - min(left.rows, right.rows, matched), matched)
    else:
        rows = matched
    columns: dict[str, ColumnStats] = {}
    overlap = node.left.schema().keys() & node.right.schema().keys()
    for name, column in left.columns.items():
        columns[f"{name}{node.left_suffix}" if name in overlap else name] = column
    if node.how not in ("semi", "anti"):
        for name, column in right.columns.items():
            columns[f"{name}{node.right_suffix}" if name in overlap else name] = column
    steps.append(NodeEstimate(str(node), rows, how, guessed))
    return _Shape(rows, _capped(columns, rows), guessed)


def _pairs(on: Expr | None) -> list[tuple[str, str]]:
    if isinstance(on, Call) and on.name == "and":
        out = []
        for arg in on.args:
            nested = _pairs(arg)
            if not nested:
                return []
            out.extend(nested)
        return out
    if isinstance(on, Call) and on.name == "eq" and all(isinstance(a, Column) for a in on.args):
        return [(on.args[0].name, on.args[1].name)]  # type: ignore[union-attr]
    return []


# ------------------------------------------------------------- selectivity


def _selectivity(expr: Expr, shape: _Shape) -> tuple[float, str, bool]:
    """The share of rows a predicate keeps, how it was worked out, and whether it is a guess."""
    if isinstance(expr, Literal) and isinstance(expr.value, bool):
        return (1.0 if expr.value else 0.0), "a constant", False
    if not isinstance(expr, Call):
        return GUESS_SELECTIVITY, "a guess: a quarter of the rows", True
    name = expr.name
    if name == "and":
        a, how_a, ga = _selectivity(expr.args[0], shape)
        b, how_b, gb = _selectivity(expr.args[1], shape)
        return a * b, f"{how_a}; and {how_b}", ga or gb
    if name == "or":
        a, how_a, ga = _selectivity(expr.args[0], shape)
        b, how_b, gb = _selectivity(expr.args[1], shape)
        return min(1.0, a + b - a * b), f"{how_a}; or {how_b}", ga or gb
    if name == "not":
        a, how_a, ga = _selectivity(expr.args[0], shape)
        return max(0.0, 1.0 - a), f"not ({how_a})", ga
    column, value = _column_and_constant(expr)
    stats = shape.columns.get(column) if column else None
    if name == "is_null" and column:
        if stats is None:
            return 0.1, f"a guess: a tenth of {column} empty", True
        return stats.empty_share, f"{stats.empty_share:.0%} of {column} empty", False
    if name == "is_not_null" and column:
        if stats is None:
            return 0.9, f"a guess: nine tenths of {column} filled", True
        return 1.0 - stats.empty_share, f"{1.0 - stats.empty_share:.0%} of {column} filled", False
    if stats is None or column is None:
        return GUESS_SELECTIVITY, "a guess: a quarter of the rows", True
    filled = 1.0 - stats.empty_share
    if name == "eq":
        share = _equal_share(stats, value, shape.rows)
        return share, f"{column} = {value!r}: {share:.1%} of rows", stats.distinct is None
    if name == "ne":
        share = max(0.0, filled - _equal_share(stats, value, shape.rows))
        return share, f"{column} not {value!r}: {share:.1%} of rows", stats.distinct is None
    if name == "in_list":
        values = [arg.value for arg in expr.args[1:] if isinstance(arg, Literal)]
        share = min(filled, sum(_equal_share(stats, v, shape.rows) for v in values))
        return share, f"{column} one of {len(values)} values: {share:.1%} of rows", stats.distinct is None
    if name in ("lt", "le", "gt", "ge"):
        flipped = isinstance(expr.args[0], Literal)
        below = _share_below(stats, value)
        if below is None:
            return GUESS_RANGE, f"a guess: a third of {column}", True
        keeps_below = (name in ("lt", "le")) != flipped
        share = filled * (below if keeps_below else 1.0 - below)
        return share, f"{column} range: {share:.1%} of rows, from its {'histogram' if stats.bounds else 'lowest and highest'}", False
    return GUESS_SELECTIVITY, f"a guess: a quarter of the rows for {name}", True


def _column_and_constant(expr: Call) -> tuple[str | None, Any]:
    columns = [arg for arg in expr.args if isinstance(arg, Column)]
    constants = [arg for arg in expr.args if isinstance(arg, Literal)]
    if len(columns) != 1:
        return None, None
    return columns[0].name, constants[0].value if constants else None


def _equal_share(stats: ColumnStats, value: Any, rows: float) -> float:
    filled = 1.0 - stats.empty_share
    text = str(value)
    total = sum(count for _, count in stats.common) or 0
    for common_value, count in stats.common:
        if common_value == text or (_number(common_value) is not None and _number(common_value) == _number(value)):
            return min(filled, count / rows) if rows else 0.0
    if not stats.distinct:
        return 0.1 * filled
    others = max(1, stats.distinct - len(stats.common))
    rest = max(0.0, filled - (total / rows if rows else 0.0))
    return rest / others


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point(value: Any, kind: str) -> float | None:
    """A constant where a histogram measures: numbers as they are, dates as milliseconds since 1970."""
    if kind != "datetime":
        return _number(value)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _number(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return aware.timestamp() * 1000.0
    return _number(value)


def _share_below(stats: ColumnStats, value: Any) -> float | None:
    """The share of filled rows below `value`."""
    point = _point(value, stats.kind)
    if point is None:
        return None
    if stats.bounds and stats.bucket_rows and len(stats.bounds) == len(stats.bucket_rows) + 1:
        total = float(sum(stats.bucket_rows))
        below = 0.0
        for index, count in enumerate(stats.bucket_rows):
            low, high = stats.bounds[index], stats.bounds[index + 1]
            if point >= high:
                below += count
            elif point > low:
                below += count * (point - low) / (high - low)
                break
            else:
                break
        if stats.histogram_excludes_common:
            # The commonest values are counted apart from the histogram's buckets.
            for value, count in stats.common:
                where = _point(value, stats.kind)
                total += count
                if where is not None and where < point:
                    below += count
        return min(1.0, below / total) if total else None
    low, high = _point(stats.lowest, stats.kind), _point(stats.highest, stats.kind)
    if low is None or high is None:
        return None
    if high <= low:
        return 1.0 if point > low else 0.0
    return min(1.0, max(0.0, (point - low) / (high - low)))
