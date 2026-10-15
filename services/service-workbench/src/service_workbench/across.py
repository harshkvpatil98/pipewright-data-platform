"""One query over several sources: databases and datasets together (D2, O4, O5).

A query in the SQL workbench used to run against one connection. "Across
sources" takes one `SELECT` naming tables in any of the project's database
connections and its datasets:

    SELECT c.region, SUM(o.amount) AS sales
    FROM "Shop DB".public.orders AS o
    JOIN datasets."Customers" AS c ON o.customer_id = c.id
    WHERE o.amount > 50
    GROUP BY c.region

and runs it the way a careful person would by hand:

1. **Parsed into the IR** with sqlglot. Every column is qualified by its
   table's alias (`o.amount`), so tables never clash.
2. **Rewritten** as any recipe is: filters move down to the table they read,
   each table reads only the columns used, and inner joins are put in the
   order that keeps the least in between (`ir/reorder.py`), from statistics.
3. **Split by source.** The largest part that reads only one connection runs
   there, as SQL in its own dialect; a dataset is read as the reader may see
   it; joins between sources run here.
4. **Joined adaptively.** Inner joins run smallest side first. When the side
   fetched has few keys, they go to the other source as `IN` lists, in
   batches of `IN_LIST_BATCH`, instead of reading the whole table. After each
   join the next table is chosen again from the rows that actually came back,
   so when an estimate is ten times out, an `IN` list becomes a full read or
   the other way round and the order can change, and the plan says it switched.

The plan says what each source ran, how many rows it sent, what was estimated
and why. A source that would send more than `MAX_SOURCE_ROWS` stops the
query, rather than a join quietly working from part of a table.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.memory import check_frame
from shared_python.statistics import ColumnStats, TableStats
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, UNKNOWN, PWType
from shared_python.types.lattice import timestamp
from shared_python.words import count_of

from service_transformations.ir.estimate import estimate, scan_key
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
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.reorder import reorder_joins
from service_transformations.ir.rewrites import rewrite
from service_transformations.ir.sql_backend import can_compile, to_sql

#: Rows one source may send for one query; past it the query stops.
MAX_SOURCE_ROWS = 1_000_000
#: Keys per IN list.
IN_LIST_BATCH = 1_000
#: Keys past which shipping them costs more than reading the other side whole.
IN_LIST_MAX_KEYS = 20_000
#: How far an estimate may be out before the plan is made again.
ADAPT_FACTOR = 10
#: Rows of the answer shown, as the workbench shows a query's.
RESULT_ROWS = 10_000

_DIALECTS = {"postgresql": "postgres", "postgres": "postgres", "mysql": "mysql", "sqlite": "sqlite"}


# ---------------------------------------------------------------- the tables


@dataclass
class Table:
    """One table the query names, resolved."""

    label: str
    kind: str  # "connection" or "dataset"
    origin: str
    name: str
    schema: str | None
    columns: list[tuple[str, PWType]]
    dialect: str | None = None
    stats: TableStats | None = None


class Catalogue(Protocol):
    """Where tables are found and read; the service gives the real one, tests their own."""

    def table(self, parts: list[str]) -> Table: ...

    def fetch(self, table_origin: str, dialect: str, sql: str, max_rows: int) -> pd.DataFrame: ...

    def read_dataset(self, table_origin: str) -> pd.DataFrame: ...


# ---------------------------------------------------------------- the plan


@dataclass
class SourceRead:
    source: str
    ran: str
    rows: int
    estimated: float | None
    estimate_how: str
    method: str
    duration_ms: float
    #: Where the table's statistics came from: its database's own, a sample, every row, or nowhere.
    statistics: str = ""


@dataclass
class JoinRun:
    joined: str
    method: str
    rows: int
    estimated: float | None
    note: str = ""


@dataclass
class Outcome:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sources: list[SourceRead] = field(default_factory=list)
    joins: list[JoinRun] = field(default_factory=list)
    rewrites: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


# -------------------------------------------------------------- parsing


def _sqlglot():
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:  # pragma: no cover - a dependency of this package
        raise BadRequestError("Queries across sources need the sqlglot package on this server.") from exc
    return sqlglot, exp


def parse(sql: str):
    sqlglot, exp = _sqlglot()
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise BadRequestError("Write a SELECT to run across sources.")
    try:
        statements = [s for s in sqlglot.parse(text) if s is not None]
    except Exception as exc:  # noqa: BLE001 - sqlglot's errors name the position
        raise BadRequestError(f"That is not SQL this can read: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise BadRequestError("Run one SELECT at a time across sources.")
    select = statements[0]
    if not isinstance(select, exp.Select):
        raise BadRequestError("Across sources runs a SELECT; anything that changes data runs in one connection.")
    for unsupported, words in ((exp.With, "WITH"), (exp.Subquery, "a subquery"), (exp.Window, "a window function"),
                               (exp.Union, "UNION"), (exp.Lateral, "LATERAL")):
        if select.find(unsupported) is not None:
            raise BadRequestError(f"Across sources does not handle {words} yet; run it in one connection.")
    return select


@dataclass
class _Scope:
    tables: dict[str, Table]  # by alias

    def resolve(self, table_alias: str | None, column: str) -> str:
        if table_alias:
            table = self.tables.get(table_alias) or next(
                (t for alias, t in self.tables.items() if alias.lower() == table_alias.lower()), None)
            if table is None:
                raise BadRequestError(f"No table here is called {table_alias!r}; the tables are "
                                      f"{', '.join(self.tables)}.")
            alias = next(a for a, t in self.tables.items() if t is table)
            name = _column_named(table, column)
            if name is None:
                raise BadRequestError(f"{table.label} has no column {column!r}.")
            return f"{alias}.{name}"
        found = [(alias, _column_named(table, column)) for alias, table in self.tables.items()]
        found = [(alias, name) for alias, name in found if name is not None]
        if not found:
            raise BadRequestError(f"No table here has a column {column!r}.")
        if len(found) > 1:
            raise BadRequestError(f"{column!r} is in more than one table here ({', '.join(a for a, _ in found)}); "
                                  "name the table, as in alias.column.")
        return f"{found[0][0]}.{found[0][1]}"


def _column_named(table: Table, column: str) -> str | None:
    for name, _ in table.columns:
        if name == column:
            return name
    lowered = column.lower()
    matches = [name for name, _ in table.columns if name.lower() == lowered]
    return matches[0] if len(matches) == 1 else None


_TYPES = {
    "INT": INT64, "INTEGER": INT64, "BIGINT": INT64, "SMALLINT": INT64, "TINYINT": INT64,
    "FLOAT": FLOAT64, "DOUBLE": FLOAT64, "REAL": FLOAT64, "DECIMAL": FLOAT64, "NUMERIC": FLOAT64,
    "VARCHAR": STRING, "TEXT": STRING, "CHAR": STRING, "NVARCHAR": STRING, "STRING": STRING,
    "BOOLEAN": BOOLEAN, "BOOL": BOOLEAN, "DATE": DATE, "TIMESTAMP": timestamp(), "DATETIME": timestamp(),
}


class _Translator:
    """sqlglot expressions to IR expressions, in one scope."""

    BINARY = {"EQ": "eq", "NEQ": "ne", "GT": "gt", "GTE": "ge", "LT": "lt", "LTE": "le", "And": "and", "Or": "or",
              "Add": "add", "Sub": "sub", "Mul": "mul", "Div": "div", "Mod": "mod", "DPipe": "concat"}
    FUNCTIONS = {"Upper": "upper", "Lower": "lower", "Abs": "abs", "Round": "round", "Coalesce": "coalesce",
                 "Length": "length", "Trim": "trim", "Floor": "floor", "Ceil": "ceil", "Sqrt": "sqrt", "Ln": "ln",
                 "Exp": "exp", "Pow": "power", "Substring": "substring", "Year": "year", "Month": "month",
                 "Day": "day", "Concat": "concat", "Greatest": "greatest", "Least": "least"}
    AGGREGATES = {"Sum": "sum", "Avg": "avg", "Min": "min", "Max": "max", "Median": "median",
                  "Stddev": "stddev", "Variance": "variance"}

    def __init__(self, scope: _Scope, *, outputs: dict[str, Expr] | None = None) -> None:
        self.scope = scope
        #: Names already defined above the tables (select aliases), usable in ORDER BY and HAVING.
        self.outputs = outputs or {}

    def __call__(self, node) -> Expr:
        _, exp = _sqlglot()
        kind = type(node).__name__
        if isinstance(node, exp.Paren):
            return self(node.this)
        if isinstance(node, exp.Column):
            if not node.table and node.name in self.outputs:
                return self.outputs[node.name]
            return Column(self.scope.resolve(node.table or None, node.name))
        if isinstance(node, exp.Literal):
            if node.is_string:
                return Literal(node.this, STRING)
            number = float(node.this)
            return Literal(int(number), INT64) if number.is_integer() and "." not in node.this else Literal(number, FLOAT64)
        if isinstance(node, exp.Null):
            return Literal(None, UNKNOWN)
        if isinstance(node, exp.Boolean):
            return Literal(bool(node.this), BOOLEAN)
        if kind in self.BINARY:
            return Call(self.BINARY[kind], (self(node.this), self(node.expression)))
        if isinstance(node, exp.Neg):
            return Call("neg", (self(node.this),))
        if isinstance(node, exp.Not):
            inner = node.this
            if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
                return Call("is_not_null", (self(inner.this),))
            return Call("not", (self(inner),))
        if isinstance(node, exp.Is) and isinstance(node.expression, exp.Null):
            return Call("is_null", (self(node.this),))
        if isinstance(node, exp.In):
            if node.args.get("query") is not None:
                raise BadRequestError("IN with a subquery is not handled across sources yet.")
            return Call("in_list", (self(node.this), *[self(item) for item in node.expressions]))
        if isinstance(node, exp.Between):
            return Call("between", (self(node.this), self(node.args["low"]), self(node.args["high"])))
        if isinstance(node, exp.Like):
            return self._like(node)
        if isinstance(node, exp.Case):
            branches = tuple((self(branch.this), self(branch.args["true"])) for branch in node.args.get("ifs") or [])
            default = node.args.get("default")
            return Case(branches, self(default) if default is not None else None)
        if isinstance(node, exp.Cast):
            name = node.to.this.name if hasattr(node.to.this, "name") else str(node.to.this)
            target = _TYPES.get(str(name).upper())
            if target is None:
                raise BadRequestError(f"Casting to {node.to.sql()} is not handled across sources.")
            return Cast(self(node.this), target)
        if isinstance(node, exp.Count):
            inner = node.this
            if isinstance(inner, exp.Star) or inner is None:
                return Call("count", ())
            if isinstance(inner, exp.Distinct):
                return Call("count_distinct", (self(inner.expressions[0]),))
            return Call("count", (self(inner),))
        if kind in self.AGGREGATES:
            return Call(self.AGGREGATES[kind], (self(node.this),))
        if kind in self.FUNCTIONS:
            args = [self(arg) for arg in node.iter_expressions() if not isinstance(arg, exp.DataType)]
            return Call(self.FUNCTIONS[kind], tuple(args))
        if isinstance(node, exp.Anonymous):
            from service_transformations.ir.expressions import FUNCTIONS

            name = str(node.this).lower()
            if name not in FUNCTIONS:
                raise BadRequestError(f"{name.upper()}() is not a function this knows across sources.")
            return Call(name, tuple(self(arg) for arg in node.expressions))
        raise BadRequestError(f"{node.sql()} is not something this can run across sources yet.")

    def _like(self, node) -> Expr:
        _, exp = _sqlglot()
        pattern = node.expression
        if not (isinstance(pattern, exp.Literal) and pattern.is_string):
            raise BadRequestError("LIKE across sources takes a quoted pattern.")
        text, subject = pattern.this, self(node.this)
        inner = text.strip("%")
        if "%" in inner or "_" in text:
            raise BadRequestError("LIKE across sources handles a % at either end only.")
        if text.startswith("%") and text.endswith("%") and len(text) > 1:
            return Call("contains", (subject, Literal(inner, STRING)))
        if text.endswith("%"):
            return Call("starts_with", (subject, Literal(inner, STRING)))
        if text.startswith("%"):
            return Call("ends_with", (subject, Literal(inner, STRING)))
        return Call("eq", (subject, Literal(text, STRING)))


def to_ir(select, catalogue: Catalogue) -> tuple[Node, dict[str, Table]]:
    """The query as an IR tree over qualified columns, and the tables it reads."""
    _, exp = _sqlglot()
    from_ = select.args.get("from_") or select.args.get("from")
    if from_ is None:
        raise BadRequestError("Name a table to read, as connection.schema.table or datasets.\"Name\".")
    relations = [(from_.this, None)] + [(join.this, join) for join in select.args.get("joins") or []]
    tables: dict[str, Table] = {}
    for reference, _join in relations:
        if not isinstance(reference, exp.Table):
            raise BadRequestError("Across sources reads tables; a subquery in FROM is not handled yet.")
        parts = [part for part in (reference.catalog, reference.db, reference.name) if part]
        alias = reference.alias_or_name
        if alias in tables:
            raise BadRequestError(f"Two tables here are called {alias!r}; give one an alias.")
        tables[alias] = catalogue.table(parts)
    scope = _Scope(tables)
    translate = _Translator(scope)

    tree: Node | None = None
    above: list[Expr] = []
    for reference, join in relations:
        alias = reference.alias_or_name
        relation = _relation(alias, tables[alias])
        if tree is None:
            tree = relation
            continue
        side = (join.args.get("side") or "").upper()
        kind = (join.args.get("kind") or "").upper()
        how = {"LEFT": "left", "RIGHT": "right", "FULL": "full"}.get(side, "inner")
        if kind == "CROSS":
            how = "cross"
        on = join.args.get("on")
        if join.args.get("using"):
            raise BadRequestError("Write the join condition with ON across sources, not USING.")
        if how == "cross" or on is None:
            if on is None and how != "cross":
                raise BadRequestError("Every join across sources needs ON, or say CROSS JOIN.")
            tree = Join(tree, relation, on=None, how="cross")
            continue
        left_names, right_names = set(tree.schema()), set(relation.schema())
        pairs, rest = [], []
        for part in _split_and(translate(on)):
            if isinstance(part, Call) and part.name == "eq" and all(isinstance(a, Column) for a in part.args):
                a, b = (arg.name for arg in part.args)  # type: ignore[union-attr]
                if a in left_names and b in right_names:
                    pairs.append(Call("eq", (Column(a), Column(b))))
                    continue
                if b in left_names and a in right_names:
                    pairs.append(Call("eq", (Column(b), Column(a))))
                    continue
            rest.append(part)
        if not pairs:
            raise BadRequestError("A join across sources needs at least one column equal to another (a.id = b.id).")
        if rest and how != "inner":
            raise BadRequestError("An outer join across sources joins on equal columns only; filter in WHERE.")
        tree = Join(tree, relation, on=_and(pairs), how=how)
        above.extend(rest)
    assert tree is not None
    if above:
        tree = Filter(tree, _and(above))
    where = select.args.get("where")
    if where is not None:
        tree = Filter(tree, translate(where.this))
    return _shape(select, tree, scope), tables


def _relation(alias: str, table: Table) -> Node:
    scan = Scan(table.name, tuple(table.columns), schema_name=table.schema, origin=table.origin)
    return Project(scan, tuple((f"{alias}.{name}", Column(name)) for name, _ in table.columns))


def _split_and(expr: Expr) -> list[Expr]:
    if isinstance(expr, Call) and expr.name == "and":
        return [part for arg in expr.args for part in _split_and(arg)]
    return [expr]


def _and(parts: list[Expr]) -> Expr:
    return parts[0] if len(parts) == 1 else Call("and", tuple(parts))


def _output_name(item, used: set[str]) -> str:
    _, exp = _sqlglot()
    if isinstance(item, exp.Alias):
        name = item.alias
    elif isinstance(item, exp.Column):
        name = item.name
    else:
        name = item.sql()[:60]
    base, number = name, 2
    while name in used:
        name = f"{base}_{number}"
        number += 1
    used.add(name)
    return name


def _shape(select, tree: Node, scope: _Scope) -> Node:
    """SELECT, GROUP BY, HAVING, DISTINCT, ORDER BY and LIMIT over the joined tables."""
    _, exp = _sqlglot()
    translate = _Translator(scope)
    items: list[tuple[str, Any]] = []
    used: set[str] = set()
    for item in select.expressions:
        if isinstance(item, exp.Star) or (isinstance(item, exp.Column) and isinstance(item.this, exp.Star)):
            wanted = [item.table] if isinstance(item, exp.Column) and item.table else list(scope.tables)
            for alias in wanted:
                for name, _ in scope.tables[alias].columns:
                    shown = name if name not in used else f"{alias}.{name}"
                    used.add(shown)
                    items.append((shown, exp.column(name, table=alias)))
            continue
        items.append((_output_name(item, used), item.this if isinstance(item, exp.Alias) else item))

    translated = [(name, translate(expression)) for name, expression in items]
    group = select.args.get("group")
    having = select.args.get("having")
    grouped = group is not None or any(_has_aggregate(expr) for _, expr in translated)
    order = select.args.get("order")
    distinct = select.args.get("distinct") is not None

    if grouped:
        keys = [translate(expression) for expression in (group.expressions if group else [])]
        group_by = []
        for index, key in enumerate(keys):
            named = next((name for name, expr in translated if expr == key), None)
            group_by.append((named or (key.name if isinstance(key, Column) else f"group_{index + 1}"), key))
        aggregates: list[tuple[str, Expr]] = []
        for name, expr in translated:
            for found in _aggregates_in(expr):
                if not any(found == existing for _, existing in aggregates):
                    named = name if expr == found else f"aggregate_{len(aggregates) + 1}"
                    aggregates.append((named, found))
        having_expr = translate(having.this) if having is not None else None
        if having_expr is not None:
            for found in _aggregates_in(having_expr):
                if not any(found == existing for _, existing in aggregates):
                    aggregates.append((f"aggregate_{len(aggregates) + 1}", found))
        if not aggregates:
            aggregates.append(("rows", Call("count", ())))
        replacements = {expr: Column(name) for name, expr in [*group_by, *aggregates]}
        tree = Aggregate(tree, group_by=tuple(group_by), aggregates=tuple(aggregates))
        if having_expr is not None:
            tree = Filter(tree, _replace(having_expr, replacements))
        projections = []
        for name, expr in translated:
            replaced = _replace(expr, replacements)
            leftover = replaced.columns_used() - set(tree.schema())
            if leftover:
                raise BadRequestError(f"{name} is neither grouped by nor aggregated: put it in GROUP BY, "
                                      "or wrap it in SUM, MIN, MAX or COUNT.")
            projections.append((name, replaced))
        before_projection_scope = {name: _replace(expr, replacements) for name, expr in translated}
    else:
        projections = translated
        before_projection_scope = dict(translated)

    if order is not None:
        order_translate = _Translator(scope, outputs=before_projection_scope)
        keys = []
        for ordered in order.expressions:
            expression = order_translate(ordered.this)
            if grouped:
                expression = _replace(expression, replacements)
                if expression.columns_used() - set(tree.schema()):
                    raise BadRequestError("Order grouped results by what the SELECT shows.")
            keys.append(SortKey(expression, "desc" if ordered.args.get("desc") else "asc",
                                nulls_first=bool(ordered.args.get("nulls_first"))))
        tree = Sort(tree, tuple(keys))
    tree = Project(tree, tuple(projections))
    if distinct:
        tree = Distinct(tree)
    limit, offset = select.args.get("limit"), select.args.get("offset")
    if limit is not None or offset is not None:
        count = int(limit.expression.this) if limit is not None else None
        start = int(offset.expression.this) if offset is not None else 0
        tree = Limit(tree, count=count, offset=start)
    return tree


def _has_aggregate(expr: Expr) -> bool:
    return bool(_aggregates_in(expr))


def _aggregates_in(expr: Expr) -> list[Expr]:
    """The aggregate calls themselves: SUM(x) in ROUND(SUM(x), 2), not the ROUND."""
    from service_transformations.ir.expressions import FUNCTIONS

    if isinstance(expr, Call) and FUNCTIONS[expr.name].is_aggregate:
        return [expr]
    found: list[Expr] = []
    if isinstance(expr, Call):
        for arg in expr.args:
            found.extend(_aggregates_in(arg))
    elif isinstance(expr, Case):
        for condition, value in expr.branches:
            found.extend(_aggregates_in(condition))
            found.extend(_aggregates_in(value))
        if expr.default is not None:
            found.extend(_aggregates_in(expr.default))
    elif isinstance(expr, Cast):
        found.extend(_aggregates_in(expr.value))
    return found


def _replace(expr: Expr, replacements: dict[Expr, Expr]) -> Expr:
    if expr in replacements:
        return replacements[expr]
    if isinstance(expr, Call):
        return Call(expr.name, tuple(_replace(arg, replacements) for arg in expr.args))
    if isinstance(expr, Case):
        return Case(tuple((_replace(c, replacements), _replace(v, replacements)) for c, v in expr.branches),
                    _replace(expr.default, replacements) if expr.default is not None else None)
    if isinstance(expr, Cast):
        return Cast(_replace(expr.value, replacements), expr.to)
    return expr


# -------------------------------------------------------------- planning


@dataclass
class _Piece:
    """Part of the tree one source runs whole."""

    key: str
    node: Node
    table_origin: str
    kind: str
    dialect: str | None
    label: str
    statistics: str = ""


def _origins(node: Node) -> set[str]:
    return {scan.origin or "" for scan in node.walk() if isinstance(scan, Scan)}


def _split(node: Node, tables: dict[str, Table], pieces: list[_Piece]) -> Node:
    """Replace each part a single source runs with a placeholder scan."""
    by_origin = {table.origin: table for table in tables.values()}
    origins = _origins(node)
    if len(origins) == 1:
        table = by_origin[next(iter(origins))]
        if table.kind == "connection" and can_compile(node, table.dialect):
            return _placeholder(node, table, pieces)
        if isinstance(node, Scan):
            return _placeholder(node, table, pieces)
    children = _children(node)
    if not children:
        table = by_origin.get(next(iter(origins), ""), None)
        if table is None:
            raise BadRequestError("A part of this query reads nothing this can find.")
        return _placeholder(node, table, pieces)
    return _with(node, [_split(child, tables, pieces) for child in children])


def _placeholder(node: Node, table: Table, pieces: list[_Piece]) -> Scan:
    key = f"__piece_{len(pieces)}"
    pieces.append(_Piece(key=key, node=node, table_origin=table.origin, kind=table.kind,
                         dialect=table.dialect, label=table.label,
                         statistics=table.stats.method if table.stats is not None else "none: every estimate is a guess"))
    return Scan(key, tuple(node.schema().items()), origin=key)


def _children(node: Node) -> list[Node]:
    return list(node.children()) if hasattr(node, "children") else []


def _with(node: Node, children: list[Node]) -> Node:
    if isinstance(node, Join):
        return replace(node, left=children[0], right=children[1])
    if hasattr(node, "input"):
        return replace(node, input=children[0])
    if hasattr(node, "left"):
        return replace(node, left=children[0], right=children[1])
    return node


# -------------------------------------------------------------- running


class _Runner:
    def __init__(self, catalogue: Catalogue, tables: dict[str, Table], pieces: list[_Piece],
                 stats: dict[str, TableStats | None]) -> None:
        self.catalogue = catalogue
        self.pieces = {piece.key: piece for piece in pieces}
        self.stats = stats
        self.outcome_sources: list[SourceRead] = []
        self.outcome_joins: list[JoinRun] = []
        self.notes: list[str] = []

    # -- what is known before anything runs

    def estimated(self, node: Node) -> tuple[float, str, bool]:
        """Rows `node` (which may hold placeholders) is expected to give, and the step that decided it."""
        real = self._unfold(node)
        result = estimate(real, self.stats)
        telling = next((step.how for step in reversed(result.steps) if step.how != "the rows it is given"),
                       result.steps[-1].how)
        return result.rows, telling, result.guessed

    def keyed_estimate(self, side: Node, side_column: str, keys: int) -> float:
        """Rows `side` is expected to send when asked only for `keys` keys."""
        real = self._unfold(side)
        key_type = real.schema().get(side_column, UNKNOWN)
        probe = Scan("__keys", ((side_column + "__key", key_type),))
        semi = Join(real, probe, on=Call("eq", (Column(side_column), Column(side_column + "__key"))), how="semi")
        known = {**self.stats, "__keys": TableStats(rows=keys, columns={side_column + "__key": ColumnStats(
            name=side_column + "__key", distinct=max(keys, 1))})}
        return estimate(semi, known).rows

    def in_list_pays(self, side: Node, side_column: str, keys: int) -> bool:
        """Whether reading only `keys` keys of `side` reads well under half of it, by the estimates."""
        if keys > IN_LIST_MAX_KEYS:
            return False
        whole = estimate(self._unfold(side), self.stats).rows
        return self.keyed_estimate(side, side_column, keys) < whole / 2

    def _unfold(self, node: Node) -> Node:
        if isinstance(node, Scan) and node.source in self.pieces:
            return self.pieces[node.source].node
        children = _children(node)
        return _with(node, [self._unfold(child) for child in children]) if children else node

    # -- reading a piece

    def fetch(self, key: str, *, keys: tuple[str, list[Any]] | None = None) -> pd.DataFrame:
        piece = self.pieces[key]
        started = time.perf_counter()
        placeholder = Scan(key, tuple(piece.node.schema().items()), origin=key)
        rows_expected, how, _guessed = self.estimated(placeholder)
        if keys is not None:
            rows_expected = self.keyed_estimate(placeholder, keys[0], len(keys[1]))
            how = f"{how}; then the share of rows whose keys were sent"
        if piece.kind == "dataset":
            frame = self._read_dataset(piece)
            ran, method = "read the dataset as you may see it", "all of it"
            if keys is not None:
                column, values = keys
                frame = frame[frame[column].isin(values)].reset_index(drop=True)
                method = f"only rows with the {count_of(len(values), 'key')} found on the other side"
        elif keys is None:
            sql = to_sql(piece.node, piece.dialect)
            frame = self._sql(piece, sql)
            ran, method = sql, "all of it"
        else:
            column, values = keys
            frames, statements = [], []
            batches = [values[i:i + IN_LIST_BATCH] for i in range(0, len(values), IN_LIST_BATCH)]
            key_type = piece.node.schema().get(column, UNKNOWN)
            for batch in batches:
                filtered = Filter(piece.node, Call("in_list", (Column(column), *[_literal(v, key_type) for v in batch])))
                sql = to_sql(filtered, piece.dialect)
                statements.append(sql)
                frames.append(self._sql(piece, sql))
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(piece.node.schema()))
            ran = statements[0] if len(statements) == 1 else (
                f"{statements[0]}\n-- and {count_of(len(statements) - 1, 'more batch', 'more batches')}")
            method = (f"only the {count_of(len(values), 'key')} found on the other side, as IN lists in "
                      f"{count_of(len(batches), 'batch', 'batches')}")
        check_frame(frame, where=f"Reading {piece.label}")
        self.outcome_sources.append(SourceRead(
            source=piece.label, ran=ran, rows=int(len(frame)), estimated=round(rows_expected, 1),
            estimate_how=how, method=method, duration_ms=round((time.perf_counter() - started) * 1000, 1),
            statistics=piece.statistics))
        return frame

    def _sql(self, piece: _Piece, sql: str) -> pd.DataFrame:
        frame = self.catalogue.fetch(piece.table_origin, piece.dialect or "", sql, MAX_SOURCE_ROWS + 1)
        if len(frame) > MAX_SOURCE_ROWS:
            raise BadRequestError(
                f"{piece.label} would send more than {MAX_SOURCE_ROWS:,} rows for this query, so it stopped "
                "rather than join part of a table. Filter it in WHERE, or run this in one connection.")
        # A database names the result's columns as asked; keep exactly the piece's names and order.
        frame.columns = list(piece.node.schema())
        return frame

    def _read_dataset(self, piece: _Piece) -> pd.DataFrame:
        whole = self.catalogue.read_dataset(piece.table_origin)
        tables_scan = next(scan for scan in piece.node.walk() if isinstance(scan, Scan))
        return execute(piece.node, {tables_scan.source: whole}).reset_index(drop=True)

    # -- running the local tree

    def run(self, node: Node) -> pd.DataFrame:
        if isinstance(node, Scan) and node.source in self.pieces:
            return self.fetch(node.source)
        if isinstance(node, Join) and node.how == "inner":
            return self._inner_group(node)
        if isinstance(node, Join) and node.how in ("left", "right"):
            return self._outer(node)
        children = _children(node)
        if not children:
            raise BadRequestError("A part of this query reads nothing this can find.")
        frames = [self.run(child) for child in children]
        stand_ins = [Scan(f"__input_{index}", tuple(child.schema().items())) for index, child in enumerate(children)]
        return execute(_with(node, stand_ins), {scan.source: frame for scan, frame in zip(stand_ins, frames)})

    def _outer(self, node: Join) -> pd.DataFrame:
        """A left join reads its left side first; the right side need only send matching keys (and the reverse)."""
        kept, other = (node.left, node.right) if node.how == "left" else (node.right, node.left)
        kept_frame = self.run(kept)
        other_frame = self._read_matching(other, node, kept_frame, kept_is_left=node.how == "left")
        frames = (kept_frame, other_frame) if node.how == "left" else (other_frame, kept_frame)
        stand_ins = (Scan("__left", tuple(node.left.schema().items())), Scan("__right", tuple(node.right.schema().items())))
        joined = execute(replace(node, left=stand_ins[0], right=stand_ins[1]),
                         {"__left": frames[0], "__right": frames[1]})
        estimated, _how, _ = self.estimated(node)
        self.outcome_joins.append(JoinRun(joined=_names(node), method=f"{node.how} join, here", rows=int(len(joined)),
                                          estimated=round(estimated, 1)))
        return joined

    def _read_matching(self, other: Node, join: Join, kept_frame: pd.DataFrame, *, kept_is_left: bool) -> pd.DataFrame:
        pairs = _pairs(join.on)
        if isinstance(other, Scan) and other.source in self.pieces and len(pairs) == 1:
            kept_column, other_column = pairs[0] if kept_is_left else (pairs[0][1], pairs[0][0])
            values = _distinct(kept_frame[kept_column])
            if self.in_list_pays(other, other_column, len(values)):
                return self.fetch(other.source, keys=(other_column, values))
        return self.run(other)

    def _inner_group(self, node: Join) -> pd.DataFrame:
        """Inner joins, smallest first, each next table chosen from the rows that actually came back."""
        relations, pairs = _inner_relations(node)
        planned = [self.estimated(relation)[0] for relation in relations]
        order_planned = _planned_order(relations, pairs, self)
        start = min(range(len(relations)), key=lambda index: planned[index])
        built_frame = self._materialise(relations[start])
        built_node: Node = relations[start]
        inside = {start}
        remaining = list(pairs)
        owner = {name: index for index, relation in enumerate(relations) for name in relation.schema()}
        order_actual = [start]
        while len(inside) < len(relations):
            actual_stats = _frame_stats(built_frame)
            choices = []
            for index in range(len(relations)):
                if index in inside:
                    continue
                linking = [(a, b) for a, b in remaining if index in (owner[a], owner[b])
                           and {owner[a], owner[b]} <= inside | {index}]
                if not linking:
                    continue
                stand_in = Scan("__built", tuple(built_node.schema().items()))
                candidate = _oriented_join(stand_in, self._unfold(relations[index]), linking)
                rows = estimate(candidate, {**self.stats, "__built": actual_stats}).rows
                choices.append((rows, index, linking))
            if not choices:
                raise BadRequestError("Every table in a join across sources must be joined to another on a column.")
            rows_expected, index, linking = min(choices)
            relation = relations[index]
            right_frame = self._read_side(relation, built_frame, built_node, linking, owner, inside)
            stand_left = Scan("__built", tuple(built_node.schema().items()))
            stand_right = Scan("__next", tuple(relation.schema().items()))
            join = _oriented_join(stand_left, stand_right, linking)
            built_frame = execute(join, {"__built": built_frame, "__next": right_frame})
            check_frame(built_frame, where="A join across sources")
            built_node = _oriented_join(built_node, relation, linking)
            inside.add(index)
            order_actual.append(index)
            remaining = [pair for pair in remaining if pair not in linking]
            note = ""
            if order_actual != order_planned[: len(order_actual)]:
                note = ("switched: the rows that came back were not what was estimated, so the order was "
                        "chosen again from the real number")
                if note not in self.notes:
                    self.notes.append(note)
            self.outcome_joins.append(JoinRun(joined=_names(built_node), method="inner join, here",
                                              rows=int(len(built_frame)), estimated=round(rows_expected, 1), note=note))
        if remaining:
            # Conditions between tables already joined: checked as a filter.
            built_frame = built_frame[_all_equal(built_frame, remaining)].reset_index(drop=True)
        return built_frame[list(node.schema())].reset_index(drop=True)

    def _materialise(self, relation: Node) -> pd.DataFrame:
        return self.run(relation)

    def _read_side(self, relation: Node, built: pd.DataFrame, built_node: Node, linking, owner, inside) -> pd.DataFrame:
        """The next table: only rows with keys already found, when that is cheaper; else all of it."""
        if not (isinstance(relation, Scan) and relation.source in self.pieces) or len(linking) != 1:
            return self.run(relation)
        a, b = linking[0]
        built_column, side_column = (a, b) if owner[a] in inside else (b, a)
        values = _distinct(built[built_column])
        # What the estimates alone would have done: as many keys as rows expected so far.
        keys_expected = max(1, int(self.estimated(built_node)[0]))
        planned_in_list = self.in_list_pays(relation, side_column, keys_expected)
        use_in_list = self.in_list_pays(relation, side_column, len(values))
        far_out = max(keys_expected, 1) >= ADAPT_FACTOR * max(len(values), 1) or \
            max(len(values), 1) >= ADAPT_FACTOR * max(keys_expected, 1)
        if use_in_list != planned_in_list and far_out:
            self.notes.append(
                f"switched for {self.pieces[relation.source].label}: {count_of(len(values), 'key')} came back where "
                f"about {keys_expected:,} were expected, so "
                f"{'only those keys were read' if use_in_list else 'the whole table was read'} instead")
        if use_in_list:
            return self.fetch(relation.source, keys=(side_column, values))
        return self.fetch(relation.source)


def _inner_relations(node: Join) -> tuple[list[Node], list[tuple[str, str]]]:
    relations: list[Node] = []
    pairs: list[tuple[str, str]] = []

    def collect(current: Node) -> None:
        if isinstance(current, Join) and current.how == "inner":
            pairs.extend(_pairs(current.on))
            collect(current.left)
            collect(current.right)
        else:
            relations.append(current)

    collect(node)
    return relations, pairs


def _planned_order(relations: list[Node], pairs: list[tuple[str, str]], runner: _Runner) -> list[int]:
    """The order the estimates alone would choose, to tell when the real rows changed it."""
    owner = {name: index for index, relation in enumerate(relations) for name in relation.schema()}
    sizes = [runner.estimated(relation)[0] for relation in relations]
    start = min(range(len(relations)), key=lambda index: sizes[index])
    built: Node = runner._unfold(relations[start])
    inside, order, remaining = {start}, [start], list(pairs)
    while len(inside) < len(relations):
        options = []
        for index in range(len(relations)):
            linking = [(a, b) for a, b in remaining if index not in inside and index in (owner[a], owner[b])
                       and {owner[a], owner[b]} <= inside | {index}]
            if linking:
                candidate = _oriented_join(built, runner._unfold(relations[index]), linking)
                options.append((estimate(candidate, runner.stats).rows, index, linking, candidate))
        if not options:
            break
        _rows, index, linking, built = min(options, key=lambda option: (option[0], option[1]))
        inside.add(index)
        order.append(index)
        remaining = [pair for pair in remaining if pair not in linking]
    return order


def _pairs(on: Expr | None) -> list[tuple[str, str]]:
    return [(part.args[0].name, part.args[1].name) for part in _split_and(on) if on is not None  # type: ignore[union-attr]
            and isinstance(part, Call) and part.name == "eq" and all(isinstance(a, Column) for a in part.args)]


def _oriented_join(left: Node, right: Node, pairs: list[tuple[str, str]]) -> Join:
    left_names = set(left.schema())
    conditions = [Call("eq", (Column(a), Column(b))) if a in left_names else Call("eq", (Column(b), Column(a)))
                  for a, b in pairs]
    return Join(left, right, on=_and(conditions), how="inner")


def _distinct(series: pd.Series) -> list[Any]:
    """The keys found, as plain values, empty ones left out (an empty key matches nothing)."""
    return [_plain(value) for value in pd.unique(series.dropna())]


def _plain(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _literal(value: Any, type_: PWType) -> Literal:
    if isinstance(value, bool):
        return Literal(value, BOOLEAN)
    if isinstance(value, int):
        return Literal(value, INT64)
    if isinstance(value, float):
        return Literal(value, FLOAT64)
    return Literal(str(value), STRING if type_ is UNKNOWN else type_)


def _frame_stats(frame: pd.DataFrame) -> TableStats:
    """What is known of rows that have come back: everything, exactly."""
    columns = {}
    for name in frame.columns:
        series = frame[name]
        filled = series.dropna()
        columns[str(name)] = ColumnStats(name=str(name), empty_share=1 - len(filled) / max(len(series), 1),
                                         distinct=int(filled.nunique()) if len(filled) else 0)
    return TableStats(rows=len(frame), columns=columns, method="the rows that came back")


def _all_equal(frame: pd.DataFrame, pairs: list[tuple[str, str]]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for a, b in pairs:
        mask &= frame[a].eq(frame[b]) & frame[a].notna()
    return mask


def _names(node: Node) -> str:
    labels = []
    for scan in node.walk():
        if isinstance(scan, Scan):
            labels.append(scan.source)
    return " with ".join(labels)


# -------------------------------------------------------------- the whole


def run(sql: str, catalogue: Catalogue, *, result_rows: int = RESULT_ROWS) -> Outcome:
    started = time.perf_counter()
    select = parse(sql)
    tree, tables = to_ir(select, catalogue)
    stats = {scan_key(Scan(t.name, tuple(t.columns), schema_name=t.schema, origin=t.origin)): t.stats
             for t in tables.values()}
    rewritten, applied = rewrite(tree)
    # Statistics are keyed by the table as it was named; pruning narrows its columns only.
    reordered, reordered_by = reorder_joins(rewritten, stats)
    applied = [*applied, *reordered_by]
    pieces: list[_Piece] = []
    local = _split(reordered, tables, pieces)
    runner = _Runner(catalogue, tables, pieces, stats)
    labels = {piece.key: piece.label for piece in pieces}
    frame = runner.run(local)
    check_frame(frame, where="The answer")
    for join in runner.outcome_joins:
        for key, label in labels.items():
            join.joined = join.joined.replace(key, label)
    shown = frame.head(result_rows)
    return Outcome(
        columns=[str(column) for column in frame.columns],
        rows=_json_rows(shown),
        row_count=int(len(frame)),
        truncated=len(frame) > result_rows,
        sources=runner.outcome_sources,
        joins=runner.outcome_joins,
        rewrites=list(dict.fromkeys(str(rewrite_) for rewrite_ in applied)),
        notes=runner.notes,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )


def _json_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    from service_transformations.tabular import json_preview_rows

    return json_preview_rows(frame, len(frame))


def plain_name(name: str) -> str:
    """A connection's name as typed without quotes: lower case, spaces as underscores."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

