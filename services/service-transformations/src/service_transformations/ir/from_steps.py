"""Compile transformation steps into the relational IR.

Seventeen of the twenty step types map onto the algebra directly. Three --
``split_column``, ``pivot`` and ``unpivot`` -- reshape in ways the algebra does
not model, and become :class:`Extension` nodes. That is the escape hatch doing
its job: they remain expressible and runnable, they simply never push down,
rather than being approximated as something close-but-different.

Every mapping here is held to the same bar by ``test_ir_from_steps.py``: the
IR-compiled pipeline must produce the same frame as the existing executor.
"""

from __future__ import annotations

from typing import Any

from shared_python.types import (
    BOOLEAN,
    FLOAT64,
    INT64,
    STRING,
    parse as parse_type,
    timestamp,
)

from service_transformations.ir.expressions import Call, Cast, Column, Expr, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    IRError,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    freeze_config,
    Sort,
    SortKey,
)

#: Step types with no place in the algebra. Listed rather than discovered so the
#: set is visible, and so a new step cannot quietly join them by accident.
EXTENSION_STEPS = frozenset({"split_column", "pivot", "unpivot"})

_FILTER_OPERATORS = {
    "equals": "eq",
    "not_equals": "ne",
    "greater_than": "gt",
    "greater_or_equal": "ge",
    "less_than": "lt",
    "less_or_equal": "le",
}

#: Keyed by the ENGINE's function names -- every value in
#: `service_transformations.steps.aggregate.SUPPORTED_AGGREGATIONS` must appear
#: here, and a test enforces it. An earlier version keyed on `nunique`, which
#: the engine never emits, so `count_distinct` raised "Unsupported aggregate".
_AGGREGATE_FUNCTIONS = {
    "sum": "sum",
    "mean": "avg",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "count": "count",
    "count_distinct": "count_distinct",
    "median": "median",
    "std": "stddev",
    "first": "first",
    "last": "last",
    # Convenience aliases the API has accepted historically.
    "average": "avg",
    "nunique": "count_distinct",
}

_CAST_TARGETS = {
    "int": INT64,
    "integer": INT64,
    "float": FLOAT64,
    "double": FLOAT64,
    "string": STRING,
    "str": STRING,
    "text": STRING,
    "boolean": BOOLEAN,
    "bool": BOOLEAN,
    "datetime": timestamp(),
    "timestamp": timestamp(),
}


def _identity(columns) -> tuple[tuple[str, Expr], ...]:
    return tuple((name, Column(name)) for name in columns)


def _literal_for(value: Any) -> Literal:
    if isinstance(value, bool):
        return Literal(value, BOOLEAN)
    if isinstance(value, int):
        return Literal(value, INT64)
    if isinstance(value, float):
        return Literal(value, FLOAT64)
    return Literal(value, STRING)


def _compile_tool(node: Node, config: dict[str, Any]) -> Node:
    """A tool step already knows its own IR; this just asks it.

    Imported inside the function because the tool package imports the IR, and
    the tools are what make this module's job small rather than large.
    """
    from service_transformations.tools import build as build_tool

    return build_tool(node, config)


def compile_step(node: Node, step_type: str, config: dict[str, Any]) -> Node:
    """Wrap ``node`` in whatever the step means. Raises on an unknown type."""
    if step_type == "tool":
        return _compile_tool(node, config)
    handler = _HANDLERS.get(step_type)
    if handler is None:
        raise IRError(
            f"No IR mapping for step type {step_type!r}. "
            "Add one, or list it in EXTENSION_STEPS."
        )
    return handler(node, config)


def compile_pipeline(scan: Scan, steps: list[dict[str, Any]]) -> Node:
    """Fold a list of ``{type, config}`` steps into one tree."""
    node: Node = scan
    for index, step in enumerate(steps, start=1):
        step_type = step.get("type") or step.get("step_type")
        if not step_type:
            raise IRError(f"Step {index} has no type.")
        node = compile_step(node, step_type, step.get("config") or {})
    return node


# -- projections -----------------------------------------------------------


def _select_columns(node: Node, config: dict[str, Any]) -> Node:
    return Project(node, tuple((name, Column(name)) for name in config["columns"]))


def _drop_columns(node: Node, config: dict[str, Any]) -> Node:
    dropped = set(config["columns"])
    keep = [name for name in node.schema() if name not in dropped]
    if not keep:
        raise IRError("Dropping every column would leave nothing to work with.")
    return Project(node, _identity(keep))


def _rename_columns(node: Node, config: dict[str, Any]) -> Node:
    mappings = config["mappings"]
    return Project(
        node,
        tuple((mappings.get(name, name), Column(name)) for name in node.schema()),
    )


def _cast_column_types(node: Node, config: dict[str, Any]) -> Node:
    # The step's own key is `mappings`. An earlier version read `casts`, which
    # meant the IR silently cast nothing while the engine cast everything --
    # invisible until the lineage differential test compared the two.
    casts = config.get("mappings") or config.get("casts") or {}
    projections = []
    for name in node.schema():
        target = casts.get(name)
        if target is None:
            projections.append((name, Column(name)))
            continue
        pw_type = _CAST_TARGETS.get(str(target).lower())
        if pw_type is None:
            try:
                pw_type = parse_type(str(target))
            except ValueError as exc:
                raise IRError(f"Unknown cast target {target!r} for {name!r}.") from exc
        projections.append((name, Cast(Column(name), pw_type)))
    return Project(node, tuple(projections))


def _derive_column(node: Node, config: dict[str, Any]) -> Node:
    """A derived column is a projection -- when it is written as a formula.

    This is the payoff for parsing formulas into IR rather than into a private
    AST: `=UPPER([name])` becomes a `Project` and pushes down to the source as
    `UPPER(name)`, instead of pulling the column across the network to compute
    it here.

    The older `expression` syntax has its own evaluator and stays an Extension.
    It runs identically; it simply does not push down.
    """
    target = config.get("target_column") or config.get("name") or config.get("column")
    formula = config.get("formula")

    if isinstance(formula, str) and formula.strip() and isinstance(target, str):
        from service_transformations.formula.parser import parse_formula

        try:
            expression = parse_formula(formula, columns=list(node.schema()))
        except Exception:
            # An unparseable formula is not the planner's problem to report --
            # the step's own validation gives a much better message. Fall back
            # to an Extension so planning never fails on a broken formula.
            expression = None

        if expression is not None:
            overwrite = bool(config.get("overwrite"))
            projections = [
                (name, Column(name))
                for name in node.schema()
                if name != target or not overwrite
            ]
            if overwrite and target in node.schema():
                projections = [
                    (name, expression if name == target else Column(name))
                    for name in node.schema()
                ]
            else:
                projections.append((str(target), expression))
            return Project(node, tuple(projections))

    from shared_python.types import UNKNOWN

    schema = dict(node.schema())
    schema[str(target)] = UNKNOWN
    return Extension(
        node,
        "derive_column",
        freeze_config(config),
        output_schema=tuple(schema.items()),
    )


def _trim_strings(node: Node, config: dict[str, Any]) -> Node:
    targets = set(config["columns"])
    return Project(
        node,
        tuple(
            (name, Call("trim", (Column(name),)) if name in targets else Column(name))
            for name in node.schema()
        ),
    )


def _fill_nulls(node: Node, config: dict[str, Any]) -> Node:
    strategy = config["strategy"]
    targets = set(config["columns"])
    if strategy != "constant":
        # forward/backward fill and statistical fills depend on row order or on
        # a second pass over the column; neither is a scalar expression.
        return Extension(
            node,
            "fill_nulls",
            freeze_config(config),
            output_schema=tuple(node.schema().items()),
        )
    replacement = _literal_for(config.get("constant_value"))
    return Project(
        node,
        tuple(
            (
                name,
                Call("coalesce", (Column(name), replacement))
                if name in targets
                else Column(name),
            )
            for name in node.schema()
        ),
    )


def _replace_values(node: Node, config: dict[str, Any]) -> Node:
    targets = set(config.get("columns") or [])
    find = _literal_for(config.get("find"))
    replace = _literal_for(config.get("replace"))
    return Project(
        node,
        tuple(
            (
                name,
                Call("replace", (Column(name), find, replace))
                if name in targets
                else Column(name),
            )
            for name in node.schema()
        ),
    )


def _parse_dates(node: Node, config: dict[str, Any]) -> Node:
    targets = set(config["columns"])
    return Project(
        node,
        tuple(
            (
                name,
                Cast(Column(name), timestamp()) if name in targets else Column(name),
            )
            for name in node.schema()
        ),
    )


# -- row operations --------------------------------------------------------


def _filter_rows(node: Node, config: dict[str, Any]) -> Node:
    conditions = config["conditions"]
    predicates: list[Expr] = []
    for condition in conditions:
        column = Column(condition["column"])
        operator = condition["operator"]
        value = condition["value"]
        if operator in _FILTER_OPERATORS:
            predicates.append(Call(_FILTER_OPERATORS[operator], (column, _literal_for(value))))
        elif operator == "in":
            values = value if isinstance(value, list) else [value]
            predicates.append(
                Call("in_list", (column, *[_literal_for(v) for v in values]))
            )
        elif operator == "contains":
            # The existing step matches with a regex; SQL LIKE is not the same
            # language, so this stays local rather than becoming almost-right.
            return Extension(
                node,
                "filter_rows",
                freeze_config(config),
                output_schema=tuple(node.schema().items()),
            )
        else:
            raise IRError(f"Unsupported filter operator {operator!r}.")

    predicate = predicates[0] if len(predicates) == 1 else Call("and", tuple(predicates))
    return Filter(node, predicate)


def _drop_null_rows(node: Node, config: dict[str, Any]) -> Node:
    """Drop rows with nulls.

    ``how`` is not decoration: "any" drops a row if ANY named column is null,
    "all" only if EVERY one is. An earlier version ignored it and always applied
    "any" semantics, so "all" silently deleted rows it should have kept.
    """
    columns = config.get("columns") or list(node.schema())
    how = config.get("how", "any")
    if how not in ("any", "all"):
        raise IRError(f"drop_null_rows.how must be 'any' or 'all', not {how!r}.")

    if how == "any":
        # Keep a row only when every named column has a value.
        predicates = [Call("is_not_null", (Column(name),)) for name in columns]
        combiner = "and"
    else:
        # Drop only when all are null, so keep when at least one has a value.
        predicates = [Call("is_not_null", (Column(name),)) for name in columns]
        combiner = "or"

    predicate = (
        predicates[0] if len(predicates) == 1 else Call(combiner, tuple(predicates))
    )
    return Filter(node, predicate)


def _sort_rows(node: Node, config: dict[str, Any]) -> Node:
    columns = config["columns"]
    ascending = config.get("ascending", True)
    if isinstance(ascending, bool):
        ascending = [ascending] * len(columns)
    nulls_first = config.get("na_position", "last") == "first"
    return Sort(
        node,
        tuple(
            SortKey(Column(name), "asc" if asc else "desc", nulls_first=nulls_first)
            for name, asc in zip(columns, ascending)
        ),
    )


def _limit_rows(node: Node, config: dict[str, Any]) -> Node:
    return Limit(node, count=config["count"], offset=config.get("offset", 0) or 0)


def _remove_duplicates(node: Node, config: dict[str, Any]) -> Node:
    subset = tuple(config.get("subset") or ())
    return Distinct(node, subset=subset, keep=config.get("keep", "first"))


# -- reshaping -------------------------------------------------------------


def _aggregate(node: Node, config: dict[str, Any]) -> Node:
    group_by = tuple((name, Column(name)) for name in config.get("group_by") or ())
    aggregates: list[tuple[str, Expr]] = []
    for spec in config["aggregations"]:
        column = spec["column"]
        function = spec["function"]
        name = spec.get("alias") or f"{column}_{function}"
        ir_function = _AGGREGATE_FUNCTIONS.get(function)
        if ir_function is None:
            raise IRError(f"Unsupported aggregate function {function!r}.")
        aggregates.append((name, Call(ir_function, (Column(column),))))
    return Aggregate(node, group_by=group_by, aggregates=tuple(aggregates))


def _join_datasets(node: Node, config: dict[str, Any]) -> Node:
    # The right side is another dataset resolved by StepContext at run time, so
    # the caller supplies it; without one this cannot become a Join.
    right = config.get("_right_node")
    if right is None:
        return Extension(
            node,
            "join_datasets",
            freeze_config({k: v for k, v in config.items() if k != "_right_node"}),
        )
    left_on = config.get("left_on") or config["on"]
    right_on = config.get("right_on") or config["on"]
    if isinstance(left_on, str):
        left_on = [left_on]
    if isinstance(right_on, str):
        right_on = [right_on]
    conditions = [
        Call("eq", (Column(left), Column(right_column)))
        for left, right_column in zip(left_on, right_on)
    ]
    on = conditions[0] if len(conditions) == 1 else Call("and", tuple(conditions))
    return Join(node, right, on=on, how=config.get("how", "inner"))


def _union_datasets(node: Node, config: dict[str, Any]) -> Node:
    right = config.get("_right_node")
    if right is None:
        return Extension(
            node,
            "union_datasets",
            freeze_config({k: v for k, v in config.items() if k != "_right_node"}),
        )
    kind = "union" if config.get("distinct") else "union_all"
    return SetOp(node, right, kind=kind)


def _as_extension(name: str):
    def handler(node: Node, config: dict[str, Any]) -> Node:
        return Extension(node, name, freeze_config(config))

    return handler


_HANDLERS = {
    "select_columns": _select_columns,
    "drop_columns": _drop_columns,
    "rename_columns": _rename_columns,
    "cast_column_types": _cast_column_types,
    "derive_column": _derive_column,
    "trim_strings": _trim_strings,
    "fill_nulls": _fill_nulls,
    "replace_values": _replace_values,
    "parse_dates": _parse_dates,
    "filter_rows": _filter_rows,
    "drop_null_rows": _drop_null_rows,
    "sort_rows": _sort_rows,
    "limit_rows": _limit_rows,
    "remove_duplicates": _remove_duplicates,
    "aggregate": _aggregate,
    "join_datasets": _join_datasets,
    "union_datasets": _union_datasets,
    # Reshaping the algebra does not model. Runnable, never pushed down.
    "split_column": _as_extension("split_column"),
    "pivot": _as_extension("pivot"),
    "unpivot": _as_extension("unpivot"),
}


def known_step_types() -> frozenset[str]:
    # `tool` is handled directly in `compile_step` rather than through the
    # handler table: the tool spec builds its own node, so there is nothing for
    # a handler to do beyond call it.
    return frozenset(_HANDLERS) | {"tool"}
