"""SQL to recipes: a query, with its CTEs, joins and unions, as recipe steps (E2, X3).

A dbt model, or the SQL of an Airflow task, reads several tables; a recipe
reads one dataset and brings the others in step by step. So a query becomes:

- the recipe of the table in its FROM: a dataset, or a CTE's own steps, inline;
- a "Join as SQL does" step for each JOIN (empty keys match nothing, both
  sides' columns stay), whose other side is a dataset: a table, or a CTE or
  subquery made into a recipe of its own, named after both ("customers ·
  payments");
- one SQL step for the rest (WHERE, GROUP BY, HAVING, the columns, window
  functions, DISTINCT, ORDER BY, LIMIT) over ``input``, with every column
  named as the joins left it.

UNION [ALL] becomes the union step, INTERSECT and EXCEPT the set tools, the
second branch a recipe of its own whose columns take the first branch's
names (SQL matches them by position, the union step by name). Every SQL step
is read by the SQL step's own translator before anything is made, so what
it refuses is refused here, with its reason. Nothing is approximated: where
a warehouse could mean something else (a whole number divided by a whole
number), the query is refused with what to write instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import BadRequestError
from shared_python.types import PWType
from shared_python.types.lattice import Kind

from api_gateway.conversions.model import NotConverted, RecipePlan

#: A parameter written into a query before it is parsed: dbt's {{ var('x') }}.
PARAMETER = re.compile(r"__pw_parameter_([A-Za-z_][A-Za-z0-9_]*)__")
_WHOLE = {Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64, Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64}
#: The clauses of a SELECT this reads; anything else is refused by name.
_CLAUSES = {"expressions", "from_", "joins", "where", "group", "having", "order", "limit", "offset", "distinct",
            "with_"}


def _sqlglot():
    import sqlglot
    from sqlglot import exp

    return sqlglot, exp


def parse(sql: str, what: str):
    """One statement, read as a query."""
    sqlglot, exp = _sqlglot()
    try:
        statements = [s for s in sqlglot.parse(sql.strip().rstrip(";")) if s is not None]
    except Exception as exc:  # noqa: BLE001 - sqlglot's errors name the place
        raise NotConverted(f"The SQL of {what} cannot be read: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise NotConverted(f"{what} holds {len(statements)} statements; a query here is one SELECT.")
    query = statements[0]
    if not isinstance(query, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise NotConverted(f"{what} is a {query.key.upper()} statement, not a SELECT, so it has no result to keep.")
    return query


@dataclass
class Table:
    """A table a query names: a dataset, or a query of its own (a CTE or a subquery)."""

    label: str
    dataset: str | None = None
    columns: dict[str, PWType] | None = None
    query: Any = None
    scope: "Scope | None" = None


class Scope:
    """The tables a query can name: its CTEs, then the ones around it."""

    def __init__(self, parent: "Scope | None" = None, tables: dict[str, Table] | None = None) -> None:
        self.parent = parent
        self.tables = dict(tables or {})

    def find(self, name: str) -> Table | None:
        found = self.tables.get(name) or next(
            (table for key, table in self.tables.items() if key.lower() == name.lower()), None)
        if found is None and self.parent is not None:
            return self.parent.find(name)
        return found


@dataclass
class Chain:
    """A dataset and the steps after it: what a query is, as a recipe."""

    base: str
    steps: list[dict[str, Any]]
    columns: dict[str, PWType]
    #: One line per step, for the report.
    lines: list[str] = field(default_factory=list)


class Compiler:
    """Queries to chains of steps, making a recipe for each CTE another side needs."""

    def __init__(self, *, owner: str, owner_key: str, parameters: dict[str, Any] | None = None) -> None:
        self.owner = owner
        self.owner_key = owner_key
        #: name -> its default, written in to check a query as it would run.
        self.parameters = dict(parameters or {})
        self.helpers: list[RecipePlan] = []
        self.notes: list[str] = []
        #: What each recipe made for a CTE does, step by step, by its key.
        self.lines: dict[str, list[str]] = {}
        self._chains: dict[int, Chain] = {}
        self._made: dict[tuple[int, tuple[str, ...]], tuple[str, dict[str, PWType]]] = {}

    # ------------------------------------------------------------ tables

    def chain(self, table: Table) -> Chain:
        if table.dataset is not None:
            return Chain(table.dataset, [], dict(table.columns or {}), [])
        key = id(table.query)
        if key not in self._chains:
            self._chains[key] = self.query(table.query, table.scope or Scope(), name=table.label)
        found = self._chains[key]
        return Chain(found.base, list(found.steps), dict(found.columns), list(found.lines))

    def dataset(self, table: Table, *, columns_as: list[str] | None = None) -> tuple[str, dict[str, PWType]]:
        """A dataset holding the table: itself, or a recipe made of its query."""
        if table.dataset is not None and columns_as is None:
            return table.dataset, dict(table.columns or {})
        key = (id(table.query) if table.query is not None else id(table), tuple(columns_as or ()))
        if key not in self._made:
            chain = self.chain(table)
            if not chain.steps and columns_as is None:
                # SELECT * FROM a table, with nothing else: that table itself.
                self._made[key] = (chain.base, dict(chain.columns))
                return self._made[key]
            if columns_as is not None:
                chain = self._renamed(chain, columns_as)
            if not chain.steps:
                chain = self._sql_step(chain, "SELECT * FROM input", "keeps it as it is")
            helper_key = f"{self.owner_key}·{len(self.helpers) + 1}"
            self.helpers.append(RecipePlan(
                key=helper_key, name=f"{self.owner} · {table.label}"[:160], reads=chain.base, steps=chain.steps,
                columns=chain.columns,
                description=f"Made from {table.label} in {self.owner}, which another part of it reads as a table.",
                parameters=self._parameters_in(chain.steps)))
            self.lines[helper_key] = chain.lines
            self._made[key] = (helper_key, dict(chain.columns))
        return self._made[key]

    def _renamed(self, chain: Chain, names: list[str]) -> Chain:
        _, exp = _sqlglot()
        if list(chain.columns) == names:
            return chain
        if len(chain.columns) != len(names):
            raise NotConverted(f"The two sides of a UNION have {len(names)} and {len(chain.columns)} columns.")
        select = exp.select(*[_as(exp.column(_quoted(old)), new) for old, new in zip(chain.columns, names)]
                            ).from_("input")
        return self._sql_step(chain, select.sql(), "names its columns as the first part of the UNION does")

    # ------------------------------------------------------------ queries

    def query(self, query, scope: Scope, *, name: str) -> Chain:
        _, exp = _sqlglot()
        if isinstance(query, (exp.Union, exp.Intersect, exp.Except)):
            return self._set_operation(query, scope, name)
        if isinstance(query, exp.Subquery):
            return self.query(query.this, scope, name=name)
        if not isinstance(query, exp.Select):
            raise NotConverted(f"{name} is not a SELECT.")
        for part, value in query.args.items():
            if value and part not in _CLAUSES:
                raise NotConverted(f"{name} uses {part.upper()}, which the SQL step does not run.")
        scope = self._with(query, scope)
        from_ = query.args.get("from_")
        if from_ is None:
            raise NotConverted(f"{name} reads no table (it has no FROM).")
        first, first_alias = self._table(from_.this, scope, name)
        chain = self.chain(first)
        # What each table's columns are called in the working data, by alias.
        names: dict[str, dict[str, str]] = {first_alias: {column: column for column in chain.columns}}
        order = [first_alias]
        extra_where: list[Any] = []
        joined = _Joined(star=[(column, exp.column(_quoted(column))) for column in chain.columns])
        for join in query.args.get("joins") or []:
            chain = self._join(join, scope, name, chain, names, order, extra_where, joined)
        trivial = (not query.args.get("joins") and not any(query.args.get(part) for part in (
            "where", "group", "having", "order", "limit", "offset", "distinct"))
            and len(query.expressions) == 1 and isinstance(query.expressions[0], exp.Star))
        if trivial:
            return chain
        rest = self._rest(query, names, order, extra_where, joined, name)
        return self._sql_step(chain, rest, self._describe(query))

    def _with(self, query, scope: Scope) -> Scope:
        with_ = query.args.get("with_")
        if with_ is None:
            return scope
        if with_.args.get("recursive"):
            raise NotConverted("WITH RECURSIVE repeats a query until it stops; a recipe runs its steps once.")
        inner = Scope(scope)
        for cte in with_.expressions:
            # A CTE reads the ones before it, never itself or those after.
            inner.tables[cte.alias] = Table(label=cte.alias, query=cte.this, scope=Scope(scope, dict(inner.tables)))
        return inner

    def _table(self, reference, scope: Scope, name: str) -> tuple[Table, str]:
        _, exp = _sqlglot()
        if isinstance(reference, exp.Subquery):
            alias = reference.alias_or_name or f"subquery {len(self.helpers) + 1}"
            return Table(label=alias, query=reference.this, scope=scope), alias
        if not isinstance(reference, exp.Table):
            raise NotConverted(f"{name} reads {reference.sql()[:60]}, which is not a table.")
        for part, value in reference.args.items():
            if value and part not in ("this", "db", "catalog", "alias"):
                raise NotConverted(f"{name} reads {reference.sql()[:60]} with {part.upper()}, which the SQL step "
                                   "does not run.")
        table_name = ".".join(part for part in (reference.catalog, reference.db, reference.name) if part)
        found = scope.find(table_name) or scope.find(reference.name)
        if found is None:
            raise NotConverted(f"{name} reads {table_name}, which is neither a table this knows nor a CTE.")
        return found, reference.alias_or_name

    # -------------------------------------------------------------- joins

    def _join(self, join, scope: Scope, name: str, chain: Chain, names: dict[str, dict[str, str]],
              order: list[str], extra_where: list[Any], joined: "_Joined") -> Chain:
        _, exp = _sqlglot()
        for part, value in join.args.items():
            if value and part not in ("this", "on", "using", "side", "kind"):
                raise NotConverted(f"{name} has a {join.sql()[:40]}…, a kind of join this does not convert.")
        table, alias = self._table(join.this, scope, name)
        if alias in names:
            raise NotConverted(f"{name} names two tables {alias}; give one an alias.")
        side = (join.args.get("side") or "").upper()
        kind = (join.args.get("kind") or "").upper()
        if kind in ("SEMI", "ANTI", "ASOF"):
            raise NotConverted(f"{name} has a {kind} JOIN, which this does not convert.")
        how = {"LEFT": "left", "RIGHT": "right", "FULL": "full"}.get(side, "inner")
        on, using = join.args.get("on"), join.args.get("using")
        cross = kind == "CROSS" or (on is None and not using)
        key, right_columns = self.dataset(table)
        taken = list(chain.columns)
        suffix = _suffix(alias, taken, list(right_columns))
        brought = {column: (column if column not in taken else f"{column}{suffix}") for column in right_columns}
        label = table.label
        if cross:
            if how != "inner":
                raise NotConverted(f"{name} has an outer join with no condition.")
            step = {"step_type": "join_datasets", "config": {
                "right_dataset_id": {"$dataset": key}, "how": "cross", "suffix": suffix}}
            names[alias] = brought
            order.append(alias)
            joined.star += [(column, exp.column(_quoted(brought[column]))) for column in right_columns]
            columns = {**chain.columns, **{brought[c]: t for c, t in right_columns.items()}}
            return Chain(chain.base, [*chain.steps, step], columns,
                         [*chain.lines, f"Join every row with every row of {label} (CROSS JOIN)"])
        left_on: list[str] = []
        right_on: list[str] = []
        shared: list[tuple[str, Any]] = []
        if using:
            for identifier in using:
                column = identifier.name
                left = self._resolve(None, column, names, order, name, joined)
                right = _named({c: c for c in right_columns}, column)
                if right is None:
                    raise NotConverted(f"{label} has no column {column} to join on.")
                left_on.append(left)
                right_on.append(right)
                # As SQL defines USING: one column, either side's value.
                mine, theirs = exp.column(_quoted(left)), exp.column(_quoted(brought[right]))
                shared.append((column, mine if how in ("inner", "left") else
                               theirs if how == "right" else exp.func("COALESCE", mine, theirs)))
        else:
            rest = []
            for part in _conjuncts(on):
                pair = self._equal_columns(part, names, order, alias, right_columns, name, joined)
                if pair is None:
                    rest.append(part)
                else:
                    left_on.append(pair[0])
                    right_on.append(pair[1])
            if rest and how != "inner":
                raise NotConverted(f"{name} joins {how.upper()} on more than equal columns "
                                   f"({rest[0].sql()[:60]}), which changes which rows are kept unmatched.")
            # For an inner join, the rest of the condition is a filter after it, as SQL defines it.
            extra_where.extend(rest)
            if not left_on:
                raise NotConverted(f"{name} joins {label} on no equal columns.")
        names[alias] = brought
        order.append(alias)
        if shared:
            # SELECT * gives the USING columns first, then each side's others.
            used = {column.lower() for column, _ in shared}
            joined.star = [*shared, *[(c, e) for c, e in joined.star if c.lower() not in used],
                           *[(c, exp.column(_quoted(brought[c]))) for c in right_columns if c.lower() not in used]]
            joined.using.update({column.lower(): expression for column, expression in shared})
        else:
            joined.star += [(column, exp.column(_quoted(brought[column]))) for column in right_columns]
        step = {"step_type": "tool", "config": {
            "tool": "join.sql", "right_dataset_id": {"$dataset": key}, "how": how, "on": left_on,
            "right_on": right_on, "bring": list(right_columns), "suffix": suffix}}
        nullable_left = how in ("right", "full")
        columns = {column: t for column, t in chain.columns.items()}
        if nullable_left:
            columns = {column: t.with_nullable(True) for column, t in columns.items()}
        for column, type_ in right_columns.items():
            columns[brought[column]] = type_.with_nullable(True) if how in ("left", "full") else type_
        words = {"inner": "Join", "left": "Join, keeping every row,", "right": "Join, keeping every row of it,",
                 "full": "Join, keeping every row of both,"}[how]
        return Chain(chain.base, [*chain.steps, step], columns,
                     [*chain.lines, f"{words} with {label} on {', '.join(right_on)} (Join as SQL does)"])

    def _equal_columns(self, part, names, order, alias: str, right_columns: dict[str, PWType], name: str,
                       joined: "_Joined"):
        _, exp = _sqlglot()
        if not isinstance(part, exp.EQ):
            return None
        a, b = part.this, part.expression
        if not (isinstance(a, exp.Column) and isinstance(b, exp.Column)):
            return None
        sides = []
        for column in (a, b):
            if column.table and column.table.lower() == alias.lower() or (
                    not column.table and column.name in right_columns
                    and not any(column.name in names[other] for other in order)):
                sides.append(("right", column.name))
            else:
                left = self._resolve(column.table or None, column.name, names, order, name, joined)
                if not isinstance(left, str):
                    return None  # a USING column, which is no one column of the left
                sides.append(("left", left))
        if {side for side, _ in sides} != {"left", "right"}:
            return None
        left = next(value for side, value in sides if side == "left")
        right = next(value for side, value in sides if side == "right")
        if right not in right_columns:
            match = [c for c in right_columns if c.lower() == right.lower()]
            if len(match) != 1:
                raise NotConverted(f"{name} joins on {right}, which the table it joins does not have.")
            right = match[0]
        return left, right

    def _resolve(self, table: str | None, column: str, names: dict[str, dict[str, str]], order: list[str],
                 name: str, joined: "_Joined | None" = None):
        """A column's working name, or for a USING column the expression it is."""
        if not table and joined is not None and column.lower() in joined.using:
            expression = joined.using[column.lower()]
            _, exp = _sqlglot()
            return expression.name if isinstance(expression, exp.Column) else expression
        if table:
            alias = next((a for a in order if a == table), None) or next(
                (a for a in order if a.lower() == table.lower()), None)
            if alias is None:
                raise NotConverted(f"{name} names {table}.{column}, and no table here is called {table}.")
            found = _named(names[alias], column)
            if found is None:
                raise NotConverted(f"{name} names {table}.{column}, which {table} does not have.")
            return found
        found = [(alias, _named(names[alias], column)) for alias in order]
        found = [(alias, working) for alias, working in found if working is not None]
        if not found:
            raise NotConverted(f"{name} names {column}, which no table here has.")
        if len(found) > 1:
            raise NotConverted(f"{name} names {column}, which {' and '.join(a for a, _ in found)} both have; "
                               "a database would refuse it too.")
        return found[0][1]

    # --------------------------------------------------------------- rest

    def _rest(self, query, names, order, extra_where, joined: "_Joined", name: str) -> str:
        """The query over input: no CTEs, no joins, every column by its working name."""
        _, exp = _sqlglot()
        select = query.copy()
        select.set("with_", None)
        select.set("joins", None)
        select.set("from_", exp.From(this=exp.to_table("input")))
        if any(node.args.get("query") is not None for node in select.find_all(exp.In)):
            raise NotConverted(f"{name} has IN (SELECT ...), which the SQL step does not run; make it a CTE and "
                               "join it.")
        for subquery in select.find_all(exp.Subquery, exp.Exists):
            raise NotConverted(f"{name} has a subquery ({subquery.sql()[:60]}), which the SQL step does not run; "
                               "make it a CTE and join it.")
        for item in select.expressions:
            if not isinstance(item, (exp.Alias, exp.Column, exp.Star)):
                raise NotConverted(f"{name} gives the column {item.sql()[:60]} no name; warehouses name it "
                                   "differently, so name it with AS.")
        if extra_where:
            condition = exp.and_(*[exp.paren(part.copy()) for part in extra_where])
            where = select.args.get("where")
            select.set("where", exp.Where(this=exp.and_(exp.paren(where.this), condition) if where else condition))
        outputs = {(item.alias or "").lower() for item in select.expressions if isinstance(item, exp.Alias)}
        ordering = {id(node) for item in (select.args.get("order").expressions if select.args.get("order") else [])
                    for node in item.walk()}
        bare = {id(item) for item in select.expressions
                if isinstance(item, exp.Column) and not isinstance(item.this, exp.Star)}
        # Every column the query names, by the name the steps before left it;
        # * is written out below, already by those names.
        for column in list(select.find_all(exp.Column)):
            if isinstance(column.this, exp.Star) or PARAMETER.fullmatch(column.name):
                continue
            if not column.table and column.name.lower() in outputs and (id(column) in ordering or not any(
                    _named(names[alias], column.name) for alias in order)):
                # A name the SELECT gives: ORDER BY reads it first, as SQL does.
                continue
            working = self._resolve(column.table or None, column.name, names, order, name, joined)
            replacement = exp.column(_quoted(working)) if isinstance(working, str) else working.copy()
            if id(column) in bare:
                # A column selected as it is keeps its own name, whatever the joins called it.
                replacement = _as(replacement, column.name)
            column.replace(replacement)
        expanded = []
        for item in select.expressions:
            if isinstance(item, exp.Star):
                expanded += [_as(expression.copy(), column) for column, expression in joined.star]
            elif isinstance(item, exp.Column) and isinstance(item.this, exp.Star):
                real = next((a for a in order if a.lower() == str(item.table).lower()), None)
                if real is None:
                    raise NotConverted(f"{name} selects {item.table}.*, and no table here is called {item.table}.")
                expanded += [_as(exp.column(_quoted(working)), column) for column, working in names[real].items()]
            else:
                expanded.append(item)
        seen: set[str] = set()
        for item in expanded:
            out = (item.alias if isinstance(item, exp.Alias) else item.name).lower()
            if out in seen:
                raise NotConverted(f"{name} gives two columns called {out}, which a table cannot hold.")
            seen.add(out)
        select.set("expressions", expanded)
        return select.sql()

    def _describe(self, query) -> str:
        parts = ["the columns"]
        for clause, words in (("where", "WHERE"), ("group", "GROUP BY"), ("having", "HAVING"),
                              ("distinct", "DISTINCT"), ("order", "ORDER BY"), ("limit", "LIMIT")):
            if query.args.get(clause):
                parts.append(words)
        return ", ".join(parts)

    # ---------------------------------------------------------- set ops

    def _set_operation(self, query, scope: Scope, name: str) -> Chain:
        _, exp = _sqlglot()
        for part, value in query.args.items():
            if value and part not in ("this", "expression", "distinct", "with_", "order", "limit", "offset", "by_name",
                                      "side", "kind"):
                raise NotConverted(f"{name} has {part.upper()} on a {query.key.upper()}, which this does not convert.")
        if query.args.get("by_name") or query.args.get("side") or query.args.get("kind"):
            raise NotConverted(f"{name} has a {query.key.upper()} of a kind this does not convert.")
        scope = self._with(query, scope)
        left = self.query(query.this, scope, name=name)
        right_table = Table(label=f"{name} (part {len(self.helpers) + 2})", query=query.expression, scope=scope)
        distinct = bool(query.args.get("distinct"))
        key, _ = self.dataset(right_table, columns_as=list(left.columns))
        if isinstance(query, exp.Union):
            step = {"step_type": "union_datasets", "config": {
                "other_dataset_id": {"$dataset": key}, "deduplicate": distinct, "column_strategy": "strict"}}
            line = "Add the rows of the second part, then remove repeated rows (UNION)" if distinct else \
                "Add the rows of the second part (UNION ALL)"
        else:
            if not distinct:
                raise NotConverted(f"{name} has {query.key.upper()} ALL, which keeps repeats in a way this does "
                                   "not convert.")
            tool = "combine.intersect" if isinstance(query, exp.Intersect) else "combine.except"
            step = {"step_type": "tool", "config": {"tool": tool, "right_dataset_id": {"$dataset": key},
                                                    "on": [], "repeats": "remove"}}
            line = f"Keep the rows the second part {'also has' if tool == 'combine.intersect' else 'does not have'}" \
                   f" ({query.key.upper()})"
        chain = Chain(left.base, [*left.steps, step], dict(left.columns), [*left.lines, line])
        if query.args.get("order") or query.args.get("limit") or query.args.get("offset"):
            tail = exp.select("*").from_("input")
            for part in ("order", "limit", "offset"):
                if query.args.get(part) is not None:
                    tail.set(part, query.args[part].copy())
            chain = self._sql_step(chain, tail.sql(), "ORDER BY or LIMIT on the whole")
        return chain

    # ---------------------------------------------------------- the step

    def _sql_step(self, chain: Chain, sql: str, words: str) -> Chain:
        """A SQL step over the chain, read by the SQL step's translator first."""
        stored = PARAMETER.sub(lambda match: "{{" + match.group(1) + "}}", sql)
        checked = PARAMETER.sub(lambda match: _sql_literal(self.parameters.get(match.group(1))), sql)
        columns = self._check(chain.columns, checked)
        step = {"step_type": "tool", "config": {"tool": "code.sql", "sql": stored}}
        return Chain(chain.base, [*chain.steps, step], columns, [*chain.lines, f"Transform with SQL: {words}"])

    def _check(self, columns: dict[str, PWType], sql: str) -> dict[str, PWType]:
        from service_transformations.ir.from_steps import compile_step
        from service_transformations.ir.nodes import Scan

        try:
            tree = compile_step(Scan("input", tuple(columns.items())), "tool", {"tool": "code.sql", "sql": sql})
        except BadRequestError as exc:
            raise NotConverted(f"The SQL step would not run it: {exc.detail}") from exc
        _refuse_whole_number_division(tree)
        return dict(tree.schema())

    def _parameters_in(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from service_transformations.parameters import used

        return [parameter_for(name, self.parameters.get(name)) for name in sorted(used(steps))]


@dataclass
class _Joined:
    """What SELECT * gives after the joins so far, and what each USING column is."""

    star: list[tuple[str, Any]]
    using: dict[str, Any] = field(default_factory=dict)


def parameter_for(name: str, default: Any) -> dict[str, Any]:
    """A recipe parameter for a value the source writes into its SQL."""
    if isinstance(default, bool):
        kind = "true or false"
    elif isinstance(default, int):
        kind = "whole number"
    elif isinstance(default, float):
        kind = "number"
    else:
        kind = "text"
    return {"name": name, "kind": kind, "default": default, "label": name.replace("_", " ").capitalize()}


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _named(columns: dict[str, str], column: str) -> str | None:
    if column in columns:
        return columns[column]
    matches = [working for name, working in columns.items() if name.lower() == column.lower()]
    return matches[0] if len(matches) == 1 else None


def _quoted(name: str):
    """An identifier, quoted only where SQL needs it: a keyword, a capital, a space."""
    _, exp = _sqlglot()
    from sqlglot.tokens import Tokenizer

    plain = re.fullmatch(r"[a-z_][a-z0-9_]*", name) is not None and name.upper() not in Tokenizer.KEYWORDS
    return exp.to_identifier(name, quoted=not plain)


def _as(expression, name: str):
    """expression AS name, or the column itself when it already has that name."""
    _, exp = _sqlglot()
    if isinstance(expression, exp.Column) and expression.name == name:
        return expression
    return exp.alias_(expression, _quoted(name))


def _suffix(alias: str, taken: list[str], right: list[str]) -> str:
    """An ending that gives the other side's clashing columns names nothing else has."""
    base = "__" + re.sub(r"[^A-Za-z0-9_]", "_", alias)
    suffix, number = base, 2
    while True:
        renamed = [f"{c}{suffix}" for c in right if c in taken]
        if not any(name in taken or name in right for name in renamed):
            return suffix
        suffix, number = f"{base}{number}", number + 1


def _conjuncts(condition) -> list[Any]:
    _, exp = _sqlglot()
    if isinstance(condition, exp.Paren):
        return _conjuncts(condition.this)
    if isinstance(condition, exp.And):
        return [*_conjuncts(condition.this), *_conjuncts(condition.expression)]
    return [condition]


def _refuse_whole_number_division(tree) -> None:
    """Refuse a whole number divided by a whole number: warehouses disagree on it."""
    from dataclasses import fields

    from service_transformations.ir.expressions import Call, Case, Cast, Expr
    from service_transformations.ir.nodes import Node

    def divides_whole(expr: Expr, schema: dict[str, PWType]) -> bool:
        if isinstance(expr, Call):
            if expr.name == "div" and len(expr.args) == 2 and all(
                    arg.type_of(schema).kind in _WHOLE for arg in expr.args):
                return True
            return any(divides_whole(arg, schema) for arg in expr.args)
        if isinstance(expr, Case):
            parts = [part for branch in expr.branches for part in branch]
            return any(divides_whole(part, schema) for part in [*parts, *([expr.default] if expr.default else [])])
        if isinstance(expr, Cast):
            return divides_whole(expr.value, schema)
        return False

    def refuse(where: str) -> None:
        raise NotConverted(
            f"{where} divides a whole number by a whole number, which warehouses do differently: PostgreSQL, "
            "Redshift and SQL Server give a whole number, Snowflake, BigQuery and DuckDB a decimal. Write one side "
            "as a decimal (amount / 100.0, or CAST(amount AS DECIMAL) / 100) to say which it means, then convert "
            "again.")

    def walk(node: Node) -> None:
        inputs = [getattr(node, f.name) for f in fields(node) if isinstance(getattr(node, f.name), Node)]
        schema: dict[str, PWType] = {}
        for child in inputs:
            schema.update(child.schema())
        for f in fields(node):
            value = getattr(node, f.name)
            if isinstance(value, Expr) and divides_whole(value, schema):
                refuse("A condition")
            if isinstance(value, tuple):
                for item in value:
                    # (name, expression) pairs: the columns a projection or an aggregate gives.
                    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
                        found = [item[1]] if isinstance(item[1], Expr) else [
                            v for v in getattr(item[1], "values", ()) if isinstance(v, Expr)]
                        if any(divides_whole(expr, schema) for expr in found):
                            refuse(f"The column {item[0]}" if not item[0].startswith(("aggregate_", "__over_"))
                                   else "A total")
                    elif isinstance(item, Expr) and divides_whole(item, schema):
                        refuse("A part of it")
                    elif hasattr(item, "expression") and isinstance(item.expression, Expr) and divides_whole(
                            item.expression, schema):
                        refuse("ORDER BY")
        for child in inputs:
            walk(child)

    walk(tree)


def compile_model(query, *, scope: Scope, owner: str, owner_key: str, parameters: dict[str, Any],
                  ) -> tuple[Chain, Compiler]:
    """A whole query as a chain, with the recipes its CTEs became."""
    compiler = Compiler(owner=owner, owner_key=owner_key, parameters=parameters)
    chain = compiler.query(query, scope, name=owner)
    if not chain.steps:
        chain = compiler._sql_step(chain, "SELECT * FROM input", "keeps it as it is")
    return chain, compiler


def dataset_table(label: str, key: str, columns: dict[str, PWType]) -> Table:
    """A table that is a dataset of these columns."""
    return Table(label=label, dataset=key, columns=dict(columns))
