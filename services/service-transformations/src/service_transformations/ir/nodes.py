"""The node algebra of the relational IR.

A small, closed set of operations that every transformation step compiles into.
The point is that there is **one** definition of what each operation means, with
two backends reading it, rather than twenty step implementations each hand-
rolling their own SQL and their own pandas and hoping the two agree.

Every node can report the schema it produces, which is what gives lineage,
type checking, and lossy-cast detection for free rather than per step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal as LiteralType

from shared_python.types import Kind, PWType, widen
from shared_python.types.lattice import UNKNOWN

from service_transformations.ir.expressions import (
    Expr,
    is_aggregate,
    supported_in,
)
from shared_python.words import count_of, listing, noun

Schema = dict[str, PWType]

JoinHow = LiteralType["inner", "left", "right", "full", "cross", "semi", "anti"]
SetOpKind = LiteralType["union", "union_all", "intersect", "except"]
SortDirection = LiteralType["asc", "desc"]


class IRError(ValueError):
    """A tree that cannot be executed. Raised while building, not while running."""


class Node:
    """Base class for every relational operation."""

    def schema(self) -> Schema:  # pragma: no cover
        raise NotImplementedError

    def children(self) -> list["Node"]:
        return []

    def walk(self):
        """Depth-first, leaves last -- the order a planner needs."""
        for child in self.children():
            yield from child.walk()
        yield self


@dataclass(frozen=True)
class Scan(Node):
    """A leaf: read a named relation with a known schema.

    `schema` qualifies the relation where it lives (`sales.orders`), and
    `origin` says which source it lives in (a connection, a dataset) when a
    tree reads from several (D2, O4): two tables named alike in two databases
    are two different scans.
    """

    source: str
    columns: tuple[tuple[str, PWType], ...]
    schema_name: str | None = None
    origin: str | None = None

    def schema(self) -> Schema:
        return dict(self.columns)

    def __str__(self) -> str:
        qualified = f"{self.schema_name}.{self.source}" if self.schema_name else self.source
        return f"Scan({qualified})"


@dataclass(frozen=True)
class Project(Node):
    """Select and derive in one node.

    Selection and derivation are the same operation -- "produce these named
    expressions" -- and keeping them separate meant `select_columns` and
    `derive_column` could disagree about column ordering.
    """

    input: Node
    projections: tuple[tuple[str, Expr], ...]

    def __post_init__(self) -> None:
        if not self.projections:
            raise IRError("A projection must produce at least one column.")
        names = [name for name, _ in self.projections]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise IRError(f"Two columns would share a name: {listing(sorted(duplicates))}.")
        incoming = self.input.schema()
        for name, expr in self.projections:
            if is_aggregate(expr):
                raise IRError(
                    f"{name!r} aggregates, which belongs in an Aggregate node "
                    "rather than a projection."
                )
            missing = expr.columns_used() - incoming.keys()
            if missing:
                raise IRError(
                    f"{name!r} uses {noun(len(missing), 'a column', 'columns')} that do not exist here: "
                    f"{listing(sorted(missing))}."
                )

    def schema(self) -> Schema:
        incoming = self.input.schema()
        return {name: expr.type_of(incoming) for name, expr in self.projections}

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        return f"Project({', '.join(n for n, _ in self.projections)})"


@dataclass(frozen=True)
class Filter(Node):
    """Keep rows where the predicate is true.

    Null is not true: SQL three-valued logic, matching every database. pandas
    would keep NaN comparisons as False anyway, so the two agree.
    """

    input: Node
    predicate: Expr

    def __post_init__(self) -> None:
        if is_aggregate(self.predicate):
            raise IRError(
                "A filter cannot aggregate; filter after aggregating instead."
            )
        incoming = self.input.schema()
        missing = self.predicate.columns_used() - incoming.keys()
        if missing:
            raise IRError(
                f"The filter uses {noun(len(missing), 'a column', 'columns')} that do not exist here: "
                f"{listing(sorted(missing))}."
            )
        result = self.predicate.type_of(incoming)
        if result.kind not in (Kind.BOOLEAN, Kind.UNKNOWN):
            raise IRError(f"A filter predicate must be boolean, not {result}.")

    def schema(self) -> Schema:
        return self.input.schema()

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        return f"Filter({self.predicate})"


@dataclass(frozen=True)
class Aggregate(Node):
    """Group and aggregate. Grouping keys keep their type; aggregates get theirs."""

    input: Node
    group_by: tuple[tuple[str, Expr], ...] = ()
    aggregates: tuple[tuple[str, Expr], ...] = ()

    def __post_init__(self) -> None:
        if not self.aggregates:
            raise IRError("An aggregation must produce at least one aggregate.")
        incoming = self.input.schema()
        for name, expr in self.group_by:
            if is_aggregate(expr):
                raise IRError(f"Grouping key {name!r} cannot itself aggregate.")
        for name, expr in self.aggregates:
            if not is_aggregate(expr):
                raise IRError(
                    f"{name!r} is in the aggregates but does not aggregate; "
                    "put it in group_by, or wrap it in min/max/sum."
                )
        names = [n for n, _ in self.group_by] + [n for n, _ in self.aggregates]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise IRError(f"Two columns would share a name: {listing(sorted(duplicates))}.")
        for name, expr in list(self.group_by) + list(self.aggregates):
            missing = expr.columns_used() - incoming.keys()
            if missing:
                raise IRError(
                    f"{name!r} uses {noun(len(missing), 'a column', 'columns')} that do not exist here: "
                    f"{listing(sorted(missing))}."
                )

    def schema(self) -> Schema:
        incoming = self.input.schema()
        out: Schema = {}
        for name, expr in self.group_by:
            out[name] = expr.type_of(incoming)
        for name, expr in self.aggregates:
            out[name] = expr.type_of(incoming)
        return out

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        keys = ", ".join(n for n, _ in self.group_by) or "-"
        return f"Aggregate(by {keys})"


@dataclass(frozen=True)
class Join(Node):
    """Combine two inputs.

    Column names that appear on both sides are suffixed rather than silently
    dropped: losing a column to a name clash is invisible until a report is
    wrong.

    **Sides in the condition are positional.** In every ``eq`` inside ``on``,
    the first operand refers to the LEFT input and the second to the RIGHT.
    A bare ``Column("region")`` cannot say which side it means, and resolving it
    by name lookup makes ``eq(region, region)`` compile to
    ``t1.region = t1.region`` -- always true, so the join silently becomes a
    cartesian product. The differential test caught exactly that.
    """

    left: Node
    right: Node
    on: Expr | None
    how: JoinHow = "inner"
    left_suffix: str = ""
    right_suffix: str = "_right"

    def __post_init__(self) -> None:
        if self.how == "cross" and self.on is not None:
            raise IRError("A cross join has no condition.")
        if self.how != "cross" and self.on is None:
            raise IRError(f"A {self.how} join needs a condition.")

    def schema(self) -> Schema:
        left = self.left.schema()
        right = self.right.schema()
        if self.how in ("semi", "anti"):
            # These filter the left side; the right contributes no columns.
            return dict(left)
        overlap = left.keys() & right.keys()
        out: Schema = {}
        for name, type_ in left.items():
            key = f"{name}{self.left_suffix}" if name in overlap else name
            # An outer join can introduce nulls on either side.
            out[key] = type_.with_nullable(True) if self.how in ("right", "full") else type_
        for name, type_ in right.items():
            key = f"{name}{self.right_suffix}" if name in overlap else name
            out[key] = (
                type_.with_nullable(True) if self.how in ("left", "full") else type_
            )
        return out

    def children(self) -> list[Node]:
        return [self.left, self.right]

    def __str__(self) -> str:
        return f"Join({self.how})"


@dataclass(frozen=True)
class SortKey:
    expr: Expr
    direction: SortDirection = "asc"
    #: Where nulls go. Stated explicitly because dialects disagree by default,
    #: and "the order changed after we moved to Postgres" is a real bug report.
    nulls_first: bool = False


@dataclass(frozen=True)
class Sort(Node):
    input: Node
    keys: tuple[SortKey, ...]

    def __post_init__(self) -> None:
        if not self.keys:
            raise IRError("A sort needs at least one key.")

    def schema(self) -> Schema:
        return self.input.schema()

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        return f"Sort({count_of(len(self.keys), 'key')})"


@dataclass(frozen=True)
class Limit(Node):
    input: Node
    count: int | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if self.count is not None and self.count < 0:
            raise IRError("A limit cannot be negative.")
        if self.offset < 0:
            raise IRError("An offset cannot be negative.")

    def schema(self) -> Schema:
        return self.input.schema()

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        return f"Limit({self.count}, offset={self.offset})"


@dataclass(frozen=True)
class Distinct(Node):
    input: Node
    #: Which columns decide identity. Empty means every column.
    subset: tuple[str, ...] = ()
    #: Which row survives. "first"/"last" need a defined order, so they are only
    #: meaningful directly above a Sort -- the pandas backend honours frame
    #: order, and SQL needs a window function.
    keep: LiteralType["first", "last", "any"] = "first"

    def __post_init__(self) -> None:
        available = self.input.schema().keys()
        missing = set(self.subset) - available
        if missing:
            raise IRError(
                f"Removing duplicates uses {noun(len(missing), 'a column', 'columns')} that do not exist here: "
                f"{listing(sorted(missing))}."
            )

    def schema(self) -> Schema:
        return self.input.schema()

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        return f"Distinct({', '.join(self.subset) or 'all columns'})"


@dataclass(frozen=True)
class SetOp(Node):
    """Union, intersect, except. Both sides must line up."""

    left: Node
    right: Node
    kind: SetOpKind = "union_all"

    def __post_init__(self) -> None:
        left = self.left.schema()
        right = self.right.schema()
        if list(left.keys()) != list(right.keys()):
            raise IRError(
                f"{self.kind} needs the same columns in the same order on both "
                f"sides. Left: {', '.join(left)}. Right: {', '.join(right)}."
            )

    def schema(self) -> Schema:
        left = self.left.schema()
        right = self.right.schema()
        out: Schema = {}
        for name in left:
            merged = widen(left[name], right[name])
            if merged is None:
                # Reporting UNKNOWN rather than picking a side: a union of a
                # zoned and a naive timestamp has no correct common type.
                merged = UNKNOWN
            out[name] = merged
        return out

    def children(self) -> list[Node]:
        return [self.left, self.right]

    def __str__(self) -> str:
        return f"SetOp({self.kind})"


@dataclass(frozen=True)
class WindowFrame:
    """Which rows of the partition a framed function sees, ending at the current row.

    ``peers`` counts every row that ties with the current one on the ordering
    (SQL's ``RANGE ... CURRENT ROW``), so the answer cannot depend on how ties
    arrive. ``rows`` counts rows one by one (``ROWS ... CURRENT ROW``), which is
    what a running total in a spreadsheet does, and which can. ``start`` is the
    number of rows before the current one (``rows`` only); None is the start of
    the partition. ``whole`` is the entire partition, whatever the order.
    """

    unit: LiteralType["peers", "rows"] = "peers"
    start: int | None = None
    whole: bool = False

    def __post_init__(self) -> None:
        if self.start is not None and (self.unit != "rows" or self.start < 0):
            raise IRError("A frame can start a number of rows back only when it counts rows.")

    def __str__(self) -> str:
        if self.whole:
            return "the whole partition"
        if self.start is None:
            return "every row so far" if self.unit == "rows" else "every row so far, ties together"
        return f"the last {self.start + 1} rows"


@dataclass(frozen=True)
class WindowCall:
    """One window function: its name in `WINDOW_FUNCTIONS`, arguments and frame."""

    function: str
    args: tuple[Expr, ...] = ()
    frame: WindowFrame = WindowFrame()

    def __post_init__(self) -> None:
        from service_transformations.ir.window_functions import WINDOW_FUNCTIONS

        spec = WINDOW_FUNCTIONS.get(self.function)
        if spec is None:
            raise IRError(
                f"There is no window function called {self.function!r}. "
                f"Known: {', '.join(sorted(WINDOW_FUNCTIONS))}."
            )
        if not spec.min_args <= len(self.args) <= spec.max_args:
            raise IRError(f"{self.function} takes {spec.min_args} to {spec.max_args} arguments, not {len(self.args)}.")
        for arg in self.args[spec.value_args:]:
            from service_transformations.ir.expressions import Literal

            if not isinstance(arg, Literal):
                raise IRError(f"{self.function}'s settings must be constants, not {arg}.")
        if (self.frame.unit != "peers" or self.frame.start is not None or self.frame.whole) and not spec.framed:
            raise IRError(f"{self.function} does not take a frame.")

    def columns_used(self) -> set[str]:
        used: set[str] = set()
        for arg in self.args:
            used |= arg.columns_used()
        return used

    def __str__(self) -> str:
        return f"{self.function}({', '.join(str(a) for a in self.args)})"


@dataclass(frozen=True)
class Window(Node):
    """Give every row values computed over the other rows of its partition.

    The rows themselves are unchanged and stay in their order; the node adds
    one column per function. Partitions are the distinct combinations of
    ``partition_by`` (an empty value is a partition of its own, as in SQL), and
    within one the rows are ordered by ``order_by`` with nulls placed as each
    key says. Which functions may push down is in `window_functions`.
    """

    input: Node
    partition_by: tuple[str, ...] = ()
    order_by: tuple[SortKey, ...] = ()
    functions: tuple[tuple[str, WindowCall], ...] = ()

    def __post_init__(self) -> None:
        from service_transformations.ir.window_functions import WINDOW_FUNCTIONS

        if not self.functions:
            raise IRError("A window must compute at least one value.")
        incoming = self.input.schema()
        missing = set(self.partition_by) - incoming.keys()
        for key in self.order_by:
            missing |= key.expr.columns_used() - incoming.keys()
        for name, call in self.functions:
            missing |= call.columns_used() - incoming.keys()
            if name in incoming:
                raise IRError(f"Column {name!r} already exists; a window adds new columns.")
            if WINDOW_FUNCTIONS[call.function].needs_order and not self.order_by:
                raise IRError(f"{call.function} needs the rows in an order; say which.")
        if missing:
            raise IRError(
                f"The window uses {noun(len(missing), 'a column', 'columns')} that do not exist here: "
                f"{listing(sorted(missing))}."
            )
        names = [name for name, _ in self.functions]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise IRError(f"Two columns would share a name: {listing(sorted(duplicates))}.")

    def schema(self) -> Schema:
        from service_transformations.ir.window_functions import WINDOW_FUNCTIONS

        incoming = self.input.schema()
        out = dict(incoming)
        for name, call in self.functions:
            spec = WINDOW_FUNCTIONS[call.function]
            out[name] = spec.result([arg.type_of(incoming) for arg in call.args[: max(spec.value_args, 1)]])
        return out

    def children(self) -> list[Node]:
        return [self.input]

    def __str__(self) -> str:
        parts = ", ".join(f"{name} = {call}" for name, call in self.functions)
        by = f" by {', '.join(self.partition_by)}" if self.partition_by else ""
        return f"Window({parts}{by})"


@dataclass(frozen=True)
class Extension(Node):
    """An operation the algebra does not model.

    The escape hatch that keeps the IR honest: a step that resists modelling is
    still expressible, it simply never pushes down. Without this, the pressure
    would be to approximate awkward steps as something close-but-different.
    """

    input: Node
    name: str
    config: tuple[tuple[str, object], ...] = ()
    #: What the step does to the schema. Unknown by default, which is why it
    #: blocks pushdown for everything above it.
    output_schema: tuple[tuple[str, PWType], ...] | None = None

    def schema(self) -> Schema:
        if self.output_schema is not None:
            return dict(self.output_schema)
        return self.input.schema()

    def children(self) -> list[Node]:
        return [self.input]

    def config_dict(self) -> dict[str, object]:
        """Recover the original config.

        Config is stored frozen so the dataclass stays hashable, which turns
        lists into tuples. Handing that straight to a step handler produces
        "config.into must be a list" -- so recovery lives here, next to the
        freezing, rather than being re-derived by each caller.
        """
        return {key: _thaw(value) for key, value in self.config}

    def __str__(self) -> str:
        return f"Extension({self.name})"


def freeze_config(config: dict[str, object]) -> tuple[tuple[str, object], ...]:
    """Make a config hashable without changing what it means."""
    return tuple(sorted((key, _freeze(value)) for key, value in config.items()))


def _freeze(value: object) -> object:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return ("__dict__", tuple(sorted((k, _freeze(v)) for k, v in value.items())))
    return value


def _thaw(value: object) -> object:
    if isinstance(value, tuple):
        if len(value) == 2 and value[0] == "__dict__":
            return {k: _thaw(v) for k, v in value[1]}
        return [_thaw(item) for item in value]
    return value


def pushable_to(dialect: str, node: Node) -> bool:
    """Whether this single node could run in ``dialect``.

    An Extension never can, by construction. Everything else depends on whether
    its expressions have lowerings.
    """
    if isinstance(node, Extension):
        return False
    if isinstance(node, Project):
        return all(supported_in(dialect, e) for _, e in node.projections)
    if isinstance(node, Filter):
        return supported_in(dialect, node.predicate)
    if isinstance(node, Aggregate):
        return all(
            supported_in(dialect, e)
            for _, e in list(node.group_by) + list(node.aggregates)
        )
    if isinstance(node, Join):
        return node.on is None or supported_in(dialect, node.on)
    if isinstance(node, Sort):
        return all(supported_in(dialect, key.expr) for key in node.keys)
    if isinstance(node, Window):
        return window_pushable(dialect, node)
    return True


def window_pushable(dialect: str, node: "Window") -> bool:
    """Whether every function of this window means exactly the same in ``dialect``."""
    from service_transformations.ir.window_functions import WINDOW_DIALECTS, WINDOW_FUNCTIONS

    if dialect not in WINDOW_DIALECTS:
        return False
    if not all(supported_in(dialect, key.expr) for key in node.order_by):
        return False
    for _, call in node.functions:
        spec = WINDOW_FUNCTIONS[call.function]
        if dialect not in spec.sql or not all(supported_in(dialect, arg) for arg in call.args):
            return False
        if spec.tie_safe is False:
            return False
        if spec.tie_safe == "frame" and node.order_by and not call.frame.whole and call.frame.unit != "peers":
            # A frame counted in rows over an ordering with ties: which tied row
            # is "before" is not something a database promises.
            return False
    return True


def describe(node: Node, indent: int = 0) -> str:
    """A readable plan tree, for the execution-plan panel and for debugging."""
    pad = "  " * indent
    lines = [f"{pad}{node}"]
    for child in node.children():
        lines.append(describe(child, indent + 1))
    return "\n".join(lines)
