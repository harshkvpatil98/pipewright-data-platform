"""Compile an IR tree to SQL.

The second of two backends. Its correctness bar is absolute: pushdown rewrites
the user's computation, so a query that returns *nearly* the right answer is
worse than one that refuses to run. Hence :class:`Unsupported` -- a dialect that
cannot express a node says so and the planner keeps that node local, rather than
emitting something that means something subtly different.
"""

from __future__ import annotations

from dataclasses import dataclass

from service_transformations.ir.expressions import (
    FUNCTIONS,
    Call,
    Case,
    Cast,
    Column,
    Expr,
    Literal,
)
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


class Unsupported(Exception):
    """This dialect cannot express this tree. Never approximate; report."""


@dataclass(frozen=True)
class Dialect:
    name: str
    quote_open: str = '"'
    quote_close: str = '"'
    #: LIMIT n OFFSET m, versus SQL Server's TOP / OFFSET-FETCH.
    supports_limit_offset: bool = True
    #: Postgres and SQLite honour NULLS FIRST/LAST; MySQL does not.
    supports_nulls_ordering: bool = True
    supports_full_outer_join: bool = True
    supports_intersect_except: bool = True
    #: MySQL writes EXCEPT as... nothing, before 8.0.31.
    except_keyword: str = "EXCEPT"

    def quote(self, identifier: str) -> str:
        escaped = identifier.replace(self.quote_close, self.quote_close * 2)
        return f"{self.quote_open}{escaped}{self.quote_close}"


POSTGRES = Dialect("postgres")
DUCKDB = Dialect("duckdb")
SQLITE = Dialect("sqlite", supports_full_outer_join=False)
MYSQL = Dialect(
    "mysql",
    quote_open="`",
    quote_close="`",
    supports_nulls_ordering=False,
    supports_intersect_except=False,
)

DIALECTS = {d.name: d for d in (POSTGRES, DUCKDB, SQLITE, MYSQL)}


def get_dialect(name: str) -> Dialect:
    if name not in DIALECTS:
        raise Unsupported(
            f"No SQL dialect named {name!r}. Known: {', '.join(sorted(DIALECTS))}."
        )
    return DIALECTS[name]


def to_sql(node: Node, dialect: str | Dialect = "postgres") -> str:
    """Compile a tree to a single SELECT statement."""
    d = get_dialect(dialect) if isinstance(dialect, str) else dialect
    return _compile(node, d, alias_seed=[0])


def _next_alias(seed: list[int]) -> str:
    seed[0] += 1
    return f"t{seed[0]}"


def _compile(node: Node, d: Dialect, alias_seed: list[int]) -> str:
    if isinstance(node, Scan):
        columns = ", ".join(d.quote(name) for name, _ in node.columns)
        return f"SELECT {columns} FROM {d.quote(node.source)}"

    if isinstance(node, Extension):
        raise Unsupported(
            f"{node.name!r} is an extension step with no SQL form; it must run locally."
        )

    if isinstance(node, Project):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        items = ", ".join(
            f"{_expr(expr, d)} AS {d.quote(name)}" for name, expr in node.projections
        )
        return f"SELECT {items} FROM ({inner}) AS {alias}"

    if isinstance(node, Filter):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        return (
            f"SELECT * FROM ({inner}) AS {alias} WHERE {_expr(node.predicate, d)}"
        )

    if isinstance(node, Aggregate):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        selects = [
            f"{_expr(expr, d)} AS {d.quote(name)}" for name, expr in node.group_by
        ] + [
            f"{_expr(expr, d)} AS {d.quote(name)}" for name, expr in node.aggregates
        ]
        sql = f"SELECT {', '.join(selects)} FROM ({inner}) AS {alias}"
        if node.group_by:
            keys = ", ".join(_expr(expr, d) for _, expr in node.group_by)
            sql += f" GROUP BY {keys}"
        return sql

    if isinstance(node, Sort):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        parts = []
        for key in node.keys:
            piece = f"{_expr(key.expr, d)} {key.direction.upper()}"
            if d.supports_nulls_ordering:
                piece += " NULLS FIRST" if key.nulls_first else " NULLS LAST"
            parts.append(piece)
        return f"SELECT * FROM ({inner}) AS {alias} ORDER BY {', '.join(parts)}"

    if isinstance(node, Limit):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        if not d.supports_limit_offset:
            raise Unsupported(f"{d.name} does not write LIMIT/OFFSET.")
        sql = f"SELECT * FROM ({inner}) AS {alias}"
        if node.count is not None:
            sql += f" LIMIT {node.count}"
        elif node.offset:
            sql += " LIMIT -1" if d.name == "sqlite" else ""
        if node.offset:
            sql += f" OFFSET {node.offset}"
        return sql

    if isinstance(node, Distinct):
        inner = _compile(node.input, d, alias_seed)
        alias = _next_alias(alias_seed)
        if not node.subset:
            return f"SELECT DISTINCT * FROM ({inner}) AS {alias}"
        # DISTINCT ON is Postgres-only; elsewhere this needs a window function,
        # which is a larger change than approximating it here would admit.
        if d.name == "postgres":
            keys = ", ".join(d.quote(name) for name in node.subset)
            return f"SELECT DISTINCT ON ({keys}) * FROM ({inner}) AS {alias}"
        raise Unsupported(
            f"{d.name} has no DISTINCT ON; de-duplicating on a subset of columns "
            "must run locally."
        )

    if isinstance(node, Join):
        return _join_sql(node, d, alias_seed)

    if isinstance(node, SetOp):
        left = _compile(node.left, d, alias_seed)
        right = _compile(node.right, d, alias_seed)
        if node.kind in ("intersect", "except") and not d.supports_intersect_except:
            raise Unsupported(f"{d.name} does not support {node.kind.upper()}.")
        keyword = {
            "union": "UNION",
            "union_all": "UNION ALL",
            "intersect": "INTERSECT",
            "except": d.except_keyword,
        }[node.kind]
        # No parentheses around the arms: SQLite rejects `(SELECT ...) UNION
        # ALL (SELECT ...)` outright. A nested set operation is wrapped in a
        # subquery instead, which every dialect accepts.
        left_sql = f"SELECT * FROM ({left}) AS {_next_alias(alias_seed)}" if isinstance(node.left, SetOp) else left
        right_sql = f"SELECT * FROM ({right}) AS {_next_alias(alias_seed)}" if isinstance(node.right, SetOp) else right
        return f"{left_sql} {keyword} {right_sql}"

    raise Unsupported(f"No SQL form for {type(node).__name__}.")


def _join_sql(node: Join, d: Dialect, alias_seed: list[int]) -> str:
    if node.how in ("semi", "anti"):
        raise Unsupported(
            f"A {node.how} join is written as EXISTS/NOT EXISTS, which needs a "
            "correlated subquery this compiler does not build yet."
        )
    if node.how == "full" and not d.supports_full_outer_join:
        raise Unsupported(f"{d.name} has no FULL OUTER JOIN.")

    left = _compile(node.left, d, alias_seed)
    right = _compile(node.right, d, alias_seed)
    left_alias = _next_alias(alias_seed)
    right_alias = _next_alias(alias_seed)

    left_schema = node.left.schema()
    right_schema = node.right.schema()
    overlap = left_schema.keys() & right_schema.keys()

    selects = [
        f"{left_alias}.{d.quote(name)} AS "
        f"{d.quote(f'{name}{node.left_suffix}' if name in overlap else name)}"
        for name in left_schema
    ] + [
        f"{right_alias}.{d.quote(name)} AS "
        f"{d.quote(f'{name}{node.right_suffix}' if name in overlap else name)}"
        for name in right_schema
    ]

    keyword = {
        "inner": "INNER JOIN",
        "left": "LEFT JOIN",
        "right": "RIGHT JOIN",
        "full": "FULL OUTER JOIN",
        "cross": "CROSS JOIN",
    }[node.how]

    sql = (
        f"SELECT {', '.join(selects)} FROM ({left}) AS {left_alias} "
        f"{keyword} ({right}) AS {right_alias}"
    )
    if node.on is not None:
        sql += f" ON {_join_condition(node.on, d, left_alias, right_alias)}"
    return sql


def _join_condition(on: Expr, d: Dialect, left_alias: str, right_alias: str) -> str:
    """Render a join condition, honouring the positional side convention.

    Resolving each Column by looking it up in a schema is wrong here: a name
    present on both sides resolves to whichever schema is checked first, and
    `eq(region, region)` becomes `t1.region = t1.region`.
    """
    if isinstance(on, Call) and on.name == "and":
        parts = [_join_condition(arg, d, left_alias, right_alias) for arg in on.args]
        return "(" + " AND ".join(parts) + ")"
    if isinstance(on, Call) and on.name in ("eq", "ne", "lt", "le", "gt", "ge"):
        left, right = on.args
        operator = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}[
            on.name
        ]
        return (
            f"({_side(left, d, left_alias)} {operator} {_side(right, d, right_alias)})"
        )
    raise Unsupported(
        f"Join conditions must be comparisons combined with AND; got {on}."
    )


def _side(expr: Expr, d: Dialect, alias: str) -> str:
    """Qualify a column with the alias of the side it belongs to."""
    if isinstance(expr, Column):
        return f"{alias}.{d.quote(expr.name)}"
    if isinstance(expr, Literal):
        return _literal(expr.value)
    raise Unsupported(
        f"A join condition operand must be a column or a literal; got {expr}."
    )


def _expr(
    expr: Expr,
    d: Dialect,
    left_alias: str | None = None,
    right_alias: str | None = None,
    left_schema: dict | None = None,
    right_schema: dict | None = None,
) -> str:
    def recurse(inner: Expr) -> str:
        return _expr(inner, d, left_alias, right_alias, left_schema, right_schema)

    if isinstance(expr, Column):
        if left_alias and left_schema is not None and expr.name in left_schema:
            return f"{left_alias}.{d.quote(expr.name)}"
        if right_alias and right_schema is not None and expr.name in right_schema:
            return f"{right_alias}.{d.quote(expr.name)}"
        return d.quote(expr.name)

    if isinstance(expr, Literal):
        return _literal(expr.value)

    if isinstance(expr, Cast):
        return f"CAST({recurse(expr.value)} AS {_sql_type(expr.to, d)})"

    if isinstance(expr, Case):
        parts = " ".join(
            f"WHEN {recurse(condition)} THEN {recurse(value)}"
            for condition, value in expr.branches
        )
        tail = f" ELSE {recurse(expr.default)}" if expr.default is not None else ""
        return f"CASE {parts}{tail} END"

    if isinstance(expr, Call):
        return _call_sql(expr, d, recurse)

    raise Unsupported(f"No SQL form for {type(expr).__name__}.")


def _call_sql(expr: Call, d: Dialect, recurse) -> str:
    signature = FUNCTIONS[expr.name]
    template = signature.sql.get(d.name)
    if template is None:
        raise Unsupported(
            f"{d.name} has no lowering for {expr.name!r}; it must run locally."
        )

    rendered = [recurse(arg) for arg in expr.args]

    if expr.name == "in_list":
        values = ", ".join(rendered[1:])
        return f"({rendered[0]} IN ({values}))"

    # Variadic functions fold pairwise so one template covers any arity.
    if expr.name in ("and", "or", "concat", "coalesce") and len(rendered) > 2:
        folded = rendered[0]
        for piece in rendered[1:]:
            folded = template.format(folded, piece)
        return folded

    if expr.name == "count" and not rendered:
        return "COUNT(*)"

    # Templates may reference fewer placeholders than there are arguments
    # (SUBSTR with two args), so pad rather than fail.
    padded = rendered + [""] * 3
    try:
        return template.format(*padded)
    except IndexError as exc:  # pragma: no cover - defensive
        raise Unsupported(f"Cannot render {expr.name!r} for {d.name}.") from exc


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _sql_type(type_, d: Dialect) -> str:
    from shared_python.types import mapping_for

    try:
        return mapping_for(d.name).from_pw(type_)
    except KeyError:
        # DuckDB shares Postgres' spelling closely enough for CAST targets.
        return mapping_for("postgres").from_pw(type_)


def can_compile(node: Node, dialect: str | Dialect = "postgres") -> bool:
    """Whether the whole tree compiles, without raising."""
    try:
        to_sql(node, dialect)
    except Unsupported:
        return False
    return True
