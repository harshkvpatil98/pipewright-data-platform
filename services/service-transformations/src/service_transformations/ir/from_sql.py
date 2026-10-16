"""SQL to the IR: one SELECT read into a tree the planner and both backends run.

Written for queries across sources (D2, O4) and shared since E1 with the SQL
step of a recipe: sqlglot parses the statement, and every column is qualified
by its table's alias (`o.amount`) so two tables never clash. Window functions
in the select list become a `Window` node (E1); WITH, subqueries, UNION and
LATERAL are refused by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from shared_python.errors import BadRequestError
from shared_python.statistics import TableStats
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, UNKNOWN, PWType
from shared_python.types.lattice import timestamp

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
    Window,
    WindowCall,
    WindowFrame,
)


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


class TableSource(Protocol):
    """Where the tables a query names are found."""

    def table(self, parts: list[str]) -> Table: ...


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
    for unsupported, words in ((exp.With, "WITH"), (exp.Subquery, "a subquery"),
                               (exp.Union, "UNION"), (exp.Lateral, "LATERAL")):
        if select.find(unsupported) is not None:
            raise BadRequestError(f"Across sources does not handle {words} yet; run it in one connection.")
    _refuse_unread_clauses(select)
    return select


#: The parts of a SELECT the translator reads. Anything else in it is refused by
#: name, not left out: a QUALIFY or DISTINCT ON passed over gave every row (E2).
_READ_CLAUSES = {"expressions", "from_", "from", "joins", "where", "group", "having", "order", "limit", "offset",
                 "distinct"}
_READ_TABLE_PARTS = {"this", "db", "catalog", "alias"}
_READ_JOIN_PARTS = {"this", "on", "using", "side", "kind"}
_CLAUSE_WORDS = {"qualify": "QUALIFY", "windows": "a named WINDOW", "sample": "TABLESAMPLE", "pivots": "PIVOT",
                 "laterals": "LATERAL", "locks": "FOR UPDATE", "into": "INTO", "hint": "a hint", "hints": "a hint",
                 "prewhere": "PREWHERE", "connect": "CONNECT BY", "kind": "SELECT AS", "version": "a version of "
                 "a table", "system_time": "a time of a table", "method": "NATURAL or another kind of join",
                 "match": "MATCH_RECOGNIZE", "settings": "SETTINGS", "format": "FORMAT", "options": "OPTIONS",
                 "exclude": "EXCLUDE", "cluster": "CLUSTER BY", "distribute": "DISTRIBUTE BY", "sort": "SORT BY"}


def _refuse_unread_clauses(select) -> None:
    _, exp = _sqlglot()

    def refuse(part: str) -> None:
        words = _CLAUSE_WORDS.get(part, part.upper())
        raise BadRequestError(f"{words[0].upper()}{words[1:]} is not something this can run yet.")

    for part, value in select.args.items():
        if value and part not in _READ_CLAUSES:
            refuse(part)
    distinct = select.args.get("distinct")
    if distinct is not None and distinct.args.get("on") is not None:
        raise BadRequestError("DISTINCT ON is not something this can run yet; rank the rows with ROW_NUMBER() "
                              "in one query and keep the first in another.")
    for table in select.find_all(exp.Table):
        for part, value in table.args.items():
            if value and part not in _READ_TABLE_PARTS:
                refuse(part)
    for join in select.args.get("joins") or []:
        for part, value in join.args.items():
            if value and part not in _READ_JOIN_PARTS:
                refuse(part)


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

    def __init__(self, scope: _Scope, *, outputs: dict[str, Expr] | None = None,
                 windows: "_Windows | None" = None) -> None:
        self.scope = scope
        #: Names already defined above the tables (select aliases), usable in ORDER BY and HAVING.
        self.outputs = outputs or {}
        #: Where window functions found in the select list are gathered.
        self.windows = windows

    def __call__(self, node) -> Expr:
        _, exp = _sqlglot()
        kind = type(node).__name__
        if isinstance(node, exp.Paren):
            return self(node.this)
        if isinstance(node, exp.Window):
            if self.windows is None:
                raise BadRequestError("A window function (OVER ...) goes in the select list.")
            return self.windows.add(node, self)
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


class _Windows:
    """Window functions in the select list, one `Window` node per distinct OVER (...)."""

    RANKING = {"RowNumber": "row_number", "Rank": "rank", "DenseRank": "dense_rank",
               "PercentRank": "percent_rank", "CumeDist": "cume_dist"}
    VALUES = {"Ntile": "ntile", "Lag": "lag", "Lead": "lead", "FirstValue": "first_value",
              "LastValue": "last_value", "NthValue": "nth_value"}
    AGGREGATES = {"Sum": "sum", "Avg": "avg", "Min": "min", "Max": "max", "Count": "count",
                  "Stddev": "stddev", "StddevSamp": "stddev"}

    def __init__(self) -> None:
        #: (partition, order) -> [(column, call)]
        self.groups: dict[tuple, list[tuple[str, WindowCall]]] = {}

    def add(self, node, translate: "_Translator") -> Expr:
        _, exp = _sqlglot()
        function = node.this
        kind = type(function).__name__
        partition = []
        for part in node.args.get("partition_by") or []:
            expression = translate(part)
            if not isinstance(expression, Column):
                raise BadRequestError("PARTITION BY takes columns across sources, not expressions.")
            partition.append(expression.name)
        order = tuple(
            SortKey(translate(item.this), "desc" if item.args.get("desc") else "asc",
                    nulls_first=bool(item.args.get("nulls_first")))
            for item in (node.args["order"].expressions if node.args.get("order") is not None else [])
        )
        args = [arg for arg in function.iter_expressions()]
        if kind in self.RANKING:
            name, values = self.RANKING[kind], ()
        elif kind in self.VALUES:
            name = self.VALUES[kind]
            values = tuple(translate(arg) for arg in args)
        elif kind in self.AGGREGATES:
            name = self.AGGREGATES[kind]
            if kind == "Count" and (not args or isinstance(args[0], exp.Star)):
                values = (Literal(1, INT64),)
            else:
                values = tuple(translate(arg) for arg in args[:1])
        else:
            raise BadRequestError(f"{function.sql()} OVER (...) is not a window function this knows across sources.")
        call = WindowCall(name, values, self._frame(node.args.get("spec"), order, name))
        column = f"__over_{sum(len(v) for v in self.groups.values()) + 1}"
        self.groups.setdefault((tuple(partition), order), []).append((column, call))
        return Column(column)

    @staticmethod
    def _frame(spec, order: tuple[SortKey, ...], name: str) -> WindowFrame:
        from service_transformations.ir.window_functions import WINDOW_FUNCTIONS

        if not WINDOW_FUNCTIONS[name].framed:
            if spec is not None:
                raise BadRequestError(f"{name.upper()} takes no frame (ROWS or RANGE).")
            return WindowFrame()
        if spec is None:
            # SQL's default: from the start to the current row's peers, or the
            # whole partition when there is no ORDER BY.
            return WindowFrame("peers") if order else WindowFrame(whole=True)
        kind = str(spec.args.get("kind") or "").upper()
        start, start_side = str(spec.args.get("start") or ""), str(spec.args.get("start_side") or "").upper()
        end, end_side = str(spec.args.get("end") or ""), str(spec.args.get("end_side") or "").upper()
        if start.upper() == "UNBOUNDED" and end.upper() == "UNBOUNDED" and end_side == "FOLLOWING":
            return WindowFrame(whole=True)
        if end.upper() != "CURRENT ROW":
            raise BadRequestError("A frame across sources ends at CURRENT ROW, or covers the whole partition.")
        if start.upper() == "UNBOUNDED" and start_side == "PRECEDING":
            return WindowFrame("rows" if kind == "ROWS" else "peers")
        if kind == "ROWS" and start.isdigit() and start_side == "PRECEDING":
            return WindowFrame("rows", int(start))
        raise BadRequestError("A frame across sources is ROWS n PRECEDING, or from UNBOUNDED PRECEDING.")

    def apply(self, tree: Node) -> Node:
        for (partition, order), calls in self.groups.items():
            tree = Window(tree, partition, order, tuple(calls))
        return tree


def to_ir(select, catalogue: TableSource) -> tuple[Node, dict[str, Table]]:
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

    windows = _Windows()
    translated = [(name, _Translator(scope, windows=windows)(expression)) for name, expression in items]
    group = select.args.get("group")
    having = select.args.get("having")
    grouped = group is not None or any(_has_aggregate(expr) for _, expr in translated)
    order = select.args.get("order")
    distinct = select.args.get("distinct") is not None

    if grouped and windows.groups:
        raise BadRequestError("A window function over grouped results is not handled across sources yet; "
                              "group in one query and rank in another.")
    tree = windows.apply(tree)
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
