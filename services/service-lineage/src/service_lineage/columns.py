"""Column-level lineage: what every output column is actually made of.

Lineage here is *derived*, never stored. A pipeline's steps and a dataset's
parent links already say everything about where a column came from, so
materialising a second copy would only create something that can go stale. The
cost is that this module has to know how each of the twenty transformation
steps reshapes a column list -- which is exactly the knowledge that makes
lineage worth anything.

The model is a symbolic execution: start from the base dataset's column names
and push them through each step, recording an edge whenever a column is
created, renamed, or rewritten. Columns that a step leaves alone get **no**
edge; a name present in both a step's input and its output passed through
untouched. That keeps the graph proportional to what actually happened instead
of to the number of columns times the number of steps.

Two things are tracked separately:

``edges``
    A column contributed to producing another column.
``reads``
    A step consulted a column without producing one -- a filter predicate, a
    sort key, a dedupe subset. Dropping such a column breaks the pipeline just
    as surely as dropping one that feeds an output, which is why impact
    analysis needs both.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from service_transformations.expressions import referenced_columns

# How one column became another.
EDGE_KINDS = (
    "identity",  # same values, carried through a structural step
    "rename",
    "cast",
    "clean",  # values rewritten in place: trims, fills, replacements
    "derive",  # computed by an expression
    "split",
    "aggregate",
    "group",  # a grouping key, which survives aggregation unchanged
    "join",
    "union",
    "pivot",
    "unpivot",
)

# Why a step looked at a column without producing one from it.
READ_PURPOSES = (
    "filter",
    "sort",
    "dedupe",
    "null_check",
    "join_key",
    "pivot_key",
    "limit",
)

# The pivot column names are whatever distinct values the data happens to hold.
DYNAMIC_COLUMN = "*"


@dataclass(frozen=True)
class ColumnEdge:
    """One column contributing to another, at one step."""

    step_index: int
    step_type: str
    from_column: str | None
    to_column: str
    kind: str
    # Set when the input column came from a second dataset rather than the
    # frame flowing through the pipeline.
    from_dataset_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_type": self.step_type,
            "from_column": self.from_column,
            "to_column": self.to_column,
            "kind": self.kind,
            "from_dataset_id": self.from_dataset_id,
        }


@dataclass(frozen=True)
class ColumnRead:
    """A column a step consulted without producing anything from it."""

    step_index: int
    step_type: str
    column: str
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_type": self.step_type,
            "column": self.column,
            "purpose": self.purpose,
        }


@dataclass
class StepLineage:
    """What one step did to the column list."""

    step_index: int
    step_type: str
    step_name: str
    input_columns: list[str]
    output_columns: list[str]
    edges: list[ColumnEdge] = field(default_factory=list)
    reads: list[ColumnRead] = field(default_factory=list)
    # Columns this step's config lists by name. The engine validates these with
    # ensure_columns_exist, so losing one of them is a hard failure rather than
    # a quiet change in results -- which is the whole distinction impact
    # analysis is built on.
    named_columns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # True when the real output columns depend on the data, not just the config.
    dynamic: bool = False

    @property
    def added_columns(self) -> list[str]:
        known = set(self.input_columns)
        return [column for column in self.output_columns if column not in known]

    @property
    def removed_columns(self) -> list[str]:
        surviving = set(self.output_columns)
        return [column for column in self.input_columns if column not in surviving]


@dataclass
class ColumnOrigin:
    """Where one traced column ultimately came from."""

    column: str
    dataset_id: str | None  # None means the pipeline's base dataset
    # The step that created it, when it was not carried in from a source.
    created_at_step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "dataset_id": self.dataset_id,
            "created_at_step": self.created_at_step,
        }


@dataclass
class ColumnTrace:
    """A backward walk from one output column to its sources."""

    column: str
    origins: list[ColumnOrigin]
    edges: list[ColumnEdge]
    unresolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "origins": [origin.to_dict() for origin in self.origins],
            "edges": [edge.to_dict() for edge in self.edges],
            "unresolved": self.unresolved,
        }


@dataclass
class PipelineLineage:
    """Column lineage for a whole pipeline."""

    base_columns: list[str]
    output_columns: list[str]
    steps: list[StepLineage]
    notes: list[str] = field(default_factory=list)

    @property
    def dynamic(self) -> bool:
        return any(step.dynamic for step in self.steps)

    def trace(self, column: str) -> ColumnTrace:
        """Walk one output column backwards to the columns it is made of."""
        return _trace_backwards(self, column)

    def downstream_of(self, base_column: str) -> list[str]:
        """Output columns that carry any value from ``base_column``."""
        affected: list[str] = []
        for column in self.output_columns:
            trace = self.trace(column)
            if any(
                origin.dataset_id is None and origin.column == base_column
                for origin in trace.origins
            ):
                affected.append(column)
        return affected

    def reads_of(self, base_column: str) -> list[ColumnRead]:
        """Steps that consult ``base_column`` without producing a column from it.

        Resolved through renames, so a filter on a column that was renamed
        three steps earlier still counts.
        """
        matches: list[ColumnRead] = []
        for read in _all_reads(self):
            for origin in _trace_name_at_step(self, read.column, read.step_index).origins:
                if origin.dataset_id is None and origin.column == base_column:
                    matches.append(read)
                    break
        return matches


# --------------------------------------------------------------------------
# Per-step transitions
# --------------------------------------------------------------------------

SchemaResolver = Callable[[str], Sequence[str] | None]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dedupe(names: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(names))


def _step_lineage(
    *,
    index: int,
    step_type: str,
    step_name: str,
    config: dict[str, Any],
    columns: list[str],
    resolve_schema: SchemaResolver | None,
) -> StepLineage:
    """Push a column list through one step, recording what changed."""

    lineage = StepLineage(
        step_index=index,
        step_type=step_type,
        step_name=step_name,
        input_columns=list(columns),
        output_columns=list(columns),
    )
    handler = _HANDLERS.get(step_type)
    if handler is None:
        lineage.notes.append(
            f"Step type '{step_type}' is not known to lineage; its columns are assumed unchanged."
        )
        lineage.dynamic = True
        return lineage

    handler(lineage, config, resolve_schema)
    return lineage


def _edge(lineage: StepLineage, source: str | None, target: str, kind: str, dataset_id: str | None = None) -> None:
    lineage.edges.append(
        ColumnEdge(
            step_index=lineage.step_index,
            step_type=lineage.step_type,
            from_column=source,
            to_column=target,
            kind=kind,
            from_dataset_id=dataset_id,
        )
    )


def _names(lineage: StepLineage, *columns: str) -> None:
    """Record that the config spelled these column names out."""
    for column in columns:
        if column and column not in lineage.named_columns:
            lineage.named_columns.append(column)


def _read(lineage: StepLineage, column: str, purpose: str) -> None:
    lineage.reads.append(
        ColumnRead(
            step_index=lineage.step_index,
            step_type=lineage.step_type,
            column=column,
            purpose=purpose,
        )
    )


def _handle_rename(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    mappings = {
        old: new.strip()
        for old, new in _mapping(config.get("mappings")).items()
        if isinstance(old, str) and isinstance(new, str) and new.strip()
    }
    lineage.output_columns = [mappings.get(column, column) for column in lineage.input_columns]
    _names(lineage, *mappings.keys())
    for old, new in mappings.items():
        if old in lineage.input_columns and old != new:
            _edge(lineage, old, new, "rename")


def _handle_cast(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    for column in _mapping(config.get("mappings")):
        _names(lineage, column)
        if column in lineage.input_columns:
            _edge(lineage, column, column, "cast")


def _handle_parse_dates(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    for column in _as_list(config.get("columns")):
        _names(lineage, column)
        if column in lineage.input_columns:
            _edge(lineage, column, column, "cast")


def _handle_clean_columns(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    for column in _as_list(config.get("columns")):
        _names(lineage, column)
        if column in lineage.input_columns:
            _edge(lineage, column, column, "clean")


def _handle_replace_values(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    column = _as_str(config.get("column"))
    if column:
        _names(lineage, column)
    if column and column in lineage.input_columns:
        _edge(lineage, column, column, "clean")


def _handle_drop_columns(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    dropped = _as_list(config.get("columns"))
    _names(lineage, *dropped)
    removed = set(dropped)
    lineage.output_columns = [column for column in lineage.input_columns if column not in removed]


def _handle_select_columns(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    selected = _dedupe(_as_list(config.get("columns")))
    _names(lineage, *selected)
    lineage.output_columns = [column for column in selected if column in lineage.input_columns]


def _handle_split_column(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    source = _as_str(config.get("column"))
    into = _as_list(config.get("into"))
    drop_original = bool(config.get("drop_original", False))

    if source:
        _names(lineage, source)
    columns = list(lineage.input_columns)
    for name in into:
        if name not in columns:
            columns.append(name)
        if source:
            _edge(lineage, source, name, "split")
    if drop_original and source:
        columns = [column for column in columns if column != source]
    lineage.output_columns = columns


def _handle_derive_column(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    target = _as_str(config.get("target_column"))
    if target is None:
        return

    sources = sorted(referenced_columns(config.get("expression", "")))
    _names(lineage, *sources)
    known = [source for source in sources if source in lineage.input_columns]
    if sources and not known:
        lineage.notes.append(
            f"'{target}' is computed from name(s) not present at this step: {', '.join(sources)}."
        )
    for source in known:
        _edge(lineage, source, target, "derive")
    if not sources:
        # A constant column has no parent, which is itself worth recording.
        _edge(lineage, None, target, "derive")

    if target not in lineage.input_columns:
        lineage.output_columns = [*lineage.input_columns, target]


def _handle_row_filter(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    conditions = config.get("conditions")
    if isinstance(conditions, list):
        for condition in conditions:
            column = _as_str(_mapping(condition).get("column"))
            if column:
                _names(lineage, column)
            if column and column in lineage.input_columns:
                _read(lineage, column, "filter")


def _handle_sort(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    for column in _as_list(config.get("columns")):
        _names(lineage, column)
        if column in lineage.input_columns:
            _read(lineage, column, "sort")


def _handle_drop_null_rows(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    configured = _as_list(config.get("columns"))
    # An omitted list means "every column", which is a read but not a name: the
    # step keeps working after one of them disappears.
    _names(lineage, *configured)
    for column in configured or lineage.input_columns:
        if column in lineage.input_columns:
            _read(lineage, column, "null_check")


def _handle_remove_duplicates(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    configured = _as_list(config.get("subset"))
    _names(lineage, *configured)
    for column in configured or lineage.input_columns:
        if column in lineage.input_columns:
            _read(lineage, column, "dedupe")


def _handle_limit_rows(lineage: StepLineage, _config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    # Row count only; no column is read or produced.
    return


def _handle_aggregate(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    group_by = _as_list(config.get("group_by"))
    outputs = list(group_by)

    _names(lineage, *group_by)
    for column in group_by:
        if column in lineage.input_columns:
            _edge(lineage, column, column, "group")

    aggregations = config.get("aggregations")
    if isinstance(aggregations, list):
        for entry in aggregations:
            entry = _mapping(entry)
            column = _as_str(entry.get("column"))
            function = _as_str(entry.get("function")) or "agg"
            alias = _as_str(entry.get("alias")) or (f"{column}_{function}" if column else None)
            if alias is None:
                continue
            outputs.append(alias)
            if column:
                _names(lineage, column)
            if column and column in lineage.input_columns:
                _edge(lineage, column, alias, "aggregate")

    lineage.output_columns = _dedupe(outputs)


def _handle_pivot(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    index_columns = [column for column in _as_list(config.get("index")) if column in lineage.input_columns]
    pivot_column = _as_str(config.get("columns"))
    values_column = _as_str(config.get("values"))

    _names(lineage, *index_columns)
    for column in index_columns:
        _edge(lineage, column, column, "group")
    if pivot_column:
        _names(lineage, pivot_column)
    if values_column:
        _names(lineage, values_column)
    if pivot_column:
        _read(lineage, pivot_column, "pivot_key")
    if values_column:
        _edge(lineage, values_column, DYNAMIC_COLUMN, "pivot")

    lineage.output_columns = [*index_columns, DYNAMIC_COLUMN]
    lineage.dynamic = True
    lineage.notes.append(
        f"The generated columns are the distinct values of '{pivot_column or '?'}', "
        "so they are only known once the pipeline runs."
    )


def _handle_unpivot(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    id_columns = [column for column in _as_list(config.get("id_columns")) if column in lineage.input_columns]
    value_columns = _as_list(config.get("value_columns"))
    if not value_columns:
        value_columns = [column for column in lineage.input_columns if column not in id_columns]

    _names(lineage, *id_columns, *_as_list(config.get("value_columns")))
    variable_name = _as_str(config.get("variable_column_name")) or "variable"
    value_name = _as_str(config.get("value_column_name")) or "value"

    for column in id_columns:
        _edge(lineage, column, column, "identity")
    for column in value_columns:
        if column not in lineage.input_columns:
            continue
        # An unpivoted column's *name* becomes data in the variable column, and
        # its values land in the value column. Both are real lineage.
        _edge(lineage, column, variable_name, "unpivot")
        _edge(lineage, column, value_name, "unpivot")

    lineage.output_columns = [*id_columns, variable_name, value_name]


def _handle_join(lineage: StepLineage, config: dict[str, Any], resolve: SchemaResolver | None) -> None:
    right_dataset_id = _as_str(config.get("right_dataset_id"))
    left_on = _as_list(config.get("left_on"))
    right_on = _as_list(config.get("right_on"))
    suffix = _as_str(config.get("suffix")) or "_right"
    select_right = config.get("select_right_columns")

    _names(lineage, *left_on)
    for column in left_on:
        if column in lineage.input_columns:
            _read(lineage, column, "join_key")

    right_columns: list[str] | None = None
    if isinstance(select_right, list):
        right_columns = _dedupe([*right_on, *_as_list(select_right)])
    elif right_dataset_id and resolve is not None:
        resolved = resolve(right_dataset_id)
        right_columns = list(resolved) if resolved is not None else None

    if right_columns is None:
        lineage.dynamic = True
        lineage.notes.append(
            "The joined dataset's columns could not be resolved, so the output column list is partial."
        )
        return

    # pandas merges same-named keys into a single column; differently named
    # keys both survive.
    shared_key_names = {left for left, right in zip(left_on, right_on, strict=False) if left == right}
    outputs = list(lineage.input_columns)
    for column in right_columns:
        if column in shared_key_names:
            continue
        # suffixes=("", suffix): the left name wins, the right one is suffixed.
        name = column if column not in lineage.input_columns else f"{column}{suffix}"
        outputs.append(name)
        _edge(lineage, column, name, "join", dataset_id=right_dataset_id)

    lineage.output_columns = _dedupe(outputs)


def _handle_union(lineage: StepLineage, config: dict[str, Any], resolve: SchemaResolver | None) -> None:
    other_dataset_id = _as_str(config.get("other_dataset_id"))
    strategy = (_as_str(config.get("column_strategy")) or "union").lower()

    other_columns: list[str] | None = None
    if other_dataset_id and resolve is not None:
        resolved = resolve(other_dataset_id)
        other_columns = list(resolved) if resolved is not None else None

    if other_columns is None:
        lineage.dynamic = True
        lineage.notes.append(
            "The other dataset's columns could not be resolved, so the output column list is partial."
        )
        return

    if strategy == "intersect":
        outputs = [column for column in lineage.input_columns if column in other_columns]
    elif strategy == "strict":
        outputs = list(lineage.input_columns)
    else:
        outputs = [
            *lineage.input_columns,
            *[column for column in other_columns if column not in lineage.input_columns],
        ]

    for column in outputs:
        if column in other_columns:
            _edge(lineage, column, column, "union", dataset_id=other_dataset_id)

    lineage.output_columns = _dedupe(outputs)


def _handle_tool(lineage: StepLineage, config: dict[str, Any], _resolve: SchemaResolver | None) -> None:
    """Lineage for the tool library, derived from the tool's own IR.

    There is deliberately no per-tool table here. A tool *is* an IR node, and
    the node already says which columns it reads and which it produces --
    keeping a second description in this module would be a second thing to get
    wrong, and it would be wrong silently, which is the failure mode lineage
    exists to prevent.
    """
    from shared_python.errors import BadRequestError
    from shared_python.types.lattice import UNKNOWN

    from service_transformations.ir.expressions import Column as IRColumn
    from service_transformations.ir.nodes import IRError, Node, Project, Scan
    from service_transformations.tools import build as build_tool

    name = _as_str(config.get("tool")) or "tool"
    source = _as_str(config.get("column"))
    if source:
        _names(lineage, source)

    scan = Scan(
        source="lineage",
        columns=tuple((column, UNKNOWN) for column in lineage.input_columns),
    )
    try:
        node: Node = build_tool(scan, dict(config))
    except (IRError, BadRequestError, ValueError, KeyError) as exc:
        # A tool that will not build is a configuration error the engine will
        # report properly. Lineage says what it does not know rather than
        # guessing a column list that would then be wrong.
        lineage.notes.append(f"Could not read the effect of '{name}': {exc}")
        lineage.dynamic = True
        return

    lineage.output_columns = list(node.schema())

    if isinstance(node, Project):
        for produced, expression in node.projections:
            if isinstance(expression, IRColumn) and expression.name == produced:
                continue  # passed through untouched
            used = sorted(expression.columns_used())
            if not used:
                _edge(lineage, None, produced, name)
            for column in used:
                if column in lineage.input_columns:
                    _edge(lineage, column, produced, name)
        return

    # A filter, sort, limit or distinct keeps every column and reads some.
    for column in sorted(_columns_read(node)):
        if column in lineage.input_columns:
            _read(lineage, column, name)


def _columns_read(node: Any) -> set[str]:
    """Every column any expression on this node mentions."""
    from service_transformations.ir.expressions import Expr

    used: set[str] = set()
    for value in vars(node).values():
        if isinstance(value, Expr):
            used |= value.columns_used()
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, Expr):
                    used |= item.columns_used()
                elif isinstance(getattr(item, "expr", None), Expr):
                    used |= item.expr.columns_used()
    return used


_HANDLERS: dict[str, Callable[[StepLineage, dict[str, Any], SchemaResolver | None], None]] = {
    "rename_columns": _handle_rename,
    "cast_column_types": _handle_cast,
    "parse_dates": _handle_parse_dates,
    "trim_strings": _handle_clean_columns,
    "fill_nulls": _handle_clean_columns,
    "replace_values": _handle_replace_values,
    "drop_columns": _handle_drop_columns,
    "select_columns": _handle_select_columns,
    "split_column": _handle_split_column,
    "derive_column": _handle_derive_column,
    "filter_rows": _handle_row_filter,
    "sort_rows": _handle_sort,
    "drop_null_rows": _handle_drop_null_rows,
    "remove_duplicates": _handle_remove_duplicates,
    "limit_rows": _handle_limit_rows,
    "aggregate": _handle_aggregate,
    "pivot": _handle_pivot,
    "unpivot": _handle_unpivot,
    "join_datasets": _handle_join,
    "union_datasets": _handle_union,
    "tool": _handle_tool,
}

# Every step type the transformation engine can run should be known here, or
# lineage silently degrades. The test suite asserts this set matches.
KNOWN_STEP_TYPES: frozenset[str] = frozenset(_HANDLERS)


# --------------------------------------------------------------------------
# Whole-pipeline assembly
# --------------------------------------------------------------------------


def build_pipeline_lineage(
    *,
    base_columns: Sequence[str],
    steps: Sequence[dict[str, Any]],
    resolve_schema: SchemaResolver | None = None,
) -> PipelineLineage:
    """Symbolically execute ``steps`` over ``base_columns``.

    ``steps`` are the stored ``steps_json`` entries: each has a ``step_type``
    and a ``config``.
    """
    columns = [str(column) for column in base_columns]
    lineage = PipelineLineage(base_columns=list(columns), output_columns=list(columns), steps=[])

    for index, raw in enumerate(steps):
        raw = _mapping(raw)
        step_type = _as_str(raw.get("step_type")) or "unknown"
        step_name = _as_str(raw.get("name")) or step_type.replace("_", " ")
        config = _mapping(raw.get("config"))

        step = _step_lineage(
            index=index,
            step_type=step_type,
            step_name=step_name,
            config=config,
            columns=columns,
            resolve_schema=resolve_schema,
        )
        lineage.steps.append(step)
        columns = list(step.output_columns)

    lineage.output_columns = columns
    if lineage.dynamic:
        lineage.notes.append(
            "Some columns depend on the data, so the output list is what the config can prove, not a guarantee."
        )
    return lineage


def _all_reads(lineage: PipelineLineage) -> list[ColumnRead]:
    return [read for step in lineage.steps for read in step.reads]


def _trace_backwards(lineage: PipelineLineage, column: str) -> ColumnTrace:
    """Walk a final output column back to its origins."""
    return _trace_name_at_step(lineage, column, len(lineage.steps))


def _trace_name_at_step(lineage: PipelineLineage, column: str, step_index: int) -> ColumnTrace:
    """Trace ``column`` as it exists entering step ``step_index``.

    ``step_index == len(steps)`` traces a final output column.
    """
    # Names currently being followed, and the external origins already found.
    frontier = {column}
    origins: dict[tuple[str | None, str], ColumnOrigin] = {}
    walked: list[ColumnEdge] = []
    unresolved = False

    for step in reversed(lineage.steps[:step_index]):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for name in frontier:
            incoming = [edge for edge in step.edges if edge.to_column == name]
            if not incoming:
                if name in step.input_columns:
                    next_frontier.add(name)  # passed through untouched
                elif step.dynamic:
                    unresolved = True
                else:
                    origins.setdefault(
                        (None, name), ColumnOrigin(column=name, dataset_id=None, created_at_step=step.step_index)
                    )
                continue

            for edge in incoming:
                walked.append(edge)
                if edge.from_dataset_id is not None:
                    key = (edge.from_dataset_id, edge.from_column or name)
                    origins.setdefault(
                        key,
                        ColumnOrigin(
                            column=edge.from_column or name,
                            dataset_id=edge.from_dataset_id,
                            created_at_step=edge.step_index,
                        ),
                    )
                elif edge.from_column is None:
                    # A literal expression: the column has no parent at all.
                    origins.setdefault(
                        (None, edge.to_column),
                        ColumnOrigin(
                            column=edge.to_column, dataset_id=None, created_at_step=edge.step_index
                        ),
                    )
                else:
                    next_frontier.add(edge.from_column)
        frontier = next_frontier

    for name in frontier:
        origins.setdefault((None, name), ColumnOrigin(column=name, dataset_id=None))

    ordered = sorted(origins.values(), key=lambda origin: (origin.dataset_id or "", origin.column))
    return ColumnTrace(column=column, origins=ordered, edges=walked, unresolved=unresolved)
