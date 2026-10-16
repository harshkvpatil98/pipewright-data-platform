"""Visual workflows to recipes: components and the connections between them (E2, X3).

Alteryx, Informatica, SSIS and Talend draw their work as components joined
by connections. Each converter describes the components it found; this
turns them into recipes:

- rows on a connection are a ``Stream``: a dataset and the steps after it;
- a component with one input adds steps to its input's stream; one that
  reads two (a join, a union, a lookup) reads the other as a dataset, which
  is the other stream's own recipe ("orders · Join (tool 7) right");
- each output (a file or a table written) is a recipe of everything before
  it; a source is a dataset the project has, or data the file carries.

Every step is compiled as the run compiles it, so a step that would not run
is refused here. A component that does not convert stops what follows it:
an output after it is made as a draft holding the steps up to it, never run,
and the report says where it stops and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from shared_python.types import PWType
from shared_python.types.lattice import UNKNOWN

from service_transformations.formula.printer import Unwritable, to_formula
from service_transformations.ir.expressions import Expr

from api_gateway.conversions.model import Conversion, NotConverted, RecipePlan, Section

_PLACEHOLDER = "00000000-0000-4000-8000-00000000ffff"


@dataclass
class Stream:
    """Rows on a connection: a dataset and the steps after it."""

    base: str
    steps: list[dict[str, Any]]
    columns: dict[str, PWType]
    lines: list[str] = field(default_factory=list)

    def then(self, step: dict[str, Any], line: str, *, columns: dict[str, PWType] | None = None) -> "Stream":
        """This stream with one more step, checked as a run compiles it and as a run checks its settings."""
        found = columns if columns is not None else _compiled_columns(self.columns, step)
        if "$dataset" not in str(step["config"]):
            _dry_run(self.columns, step)
        return Stream(self.base, [*self.steps, step], found, [*self.lines, line])


_DTYPES = {"int": "Int64", "uint": "Int64", "float": "float64", "decimal": "float64", "boolean": "boolean",
           "timestamp": "datetime64[ns]"}


def _dry_run(columns: dict[str, PWType], step: dict[str, Any]) -> None:
    """The step run on no rows of these columns: a setting the run would refuse is refused here."""
    import pandas as pd

    from service_transformations.executor import apply_transformation_steps

    def dtype(kind: PWType) -> str:
        value = kind.kind.value
        return next((found for prefix, found in _DTYPES.items() if value.startswith(prefix)), "object")

    empty = pd.DataFrame({name: pd.Series(dtype=dtype(kind)) for name, kind in columns.items()})
    try:
        apply_transformation_steps(empty, [step])
    except Exception as exc:  # noqa: BLE001 - the run's own refusal, said here instead
        detail = getattr(exc, "detail", None) or str(exc)
        raise NotConverted(f"The step would not run: {detail}") from exc


def _compiled_columns(columns: dict[str, PWType], step: dict[str, Any]) -> dict[str, PWType]:
    from service_transformations.ir.from_steps import compile_step
    from service_transformations.ir.nodes import Scan

    config = _placeheld(step["config"])
    try:
        node = compile_step(Scan("input", tuple(columns.items())), step["step_type"], config)
        return dict(node.schema())
    except Exception as exc:  # noqa: BLE001 - a step the run would refuse, with its reason
        detail = getattr(exc, "detail", None) or str(exc)
        raise NotConverted(f"The step would not run: {detail}") from exc


def _placeheld(value: Any) -> Any:
    if isinstance(value, dict):
        if "$dataset" in value:
            return _PLACEHOLDER
        return {key: _placeheld(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_placeheld(item) for item in value]
    return value


def formula_text(expr: Expr, what: str) -> str:
    try:
        return to_formula(expr)
    except Unwritable as exc:
        raise NotConverted(f"{what}: {exc.detail}") from exc


# -------------------------------------------------------------- steps


def derive(stream: Stream, target: str, expr: Expr, line: str) -> Stream:
    overwrite = target in stream.columns
    return stream.then({"step_type": "derive_column", "config": {
        "target_column": target, "formula": formula_text(expr, f"The column {target}"), "overwrite": overwrite}},
        line)


def keep_rows(stream: Stream, condition: Expr, line: str, *, keep: bool = True) -> Stream:
    """Keep the rows where the condition is true (or, with keep=False, the rest: false or empty)."""
    return stream.then({"step_type": "tool", "config": {
        "tool": "rows.filter_formula", "formula": formula_text(condition, "The condition"),
        "mode": "keep" if keep else "exclude"}}, line)


def _last(stream: Stream, step_type: str) -> bool:
    return bool(stream.steps) and stream.steps[-1]["step_type"] == step_type


def _without_last(stream: Stream) -> Stream:
    """The stream before its last step, a rename, with its columns' names as they were then."""
    back = {new: old for old, new in stream.steps[-1]["config"]["mappings"].items()}
    return Stream(stream.base, stream.steps[:-1], {back.get(name, name): kind for name, kind in stream.columns.items()},
                  stream.lines[:-1])


def select(stream: Stream, names: list[str], line: str) -> Stream:
    if names == list(stream.columns):
        return stream
    missing = [name for name in names if name not in stream.columns]
    if missing:
        raise NotConverted(f"It keeps {missing[0]}, which the rows coming in do not have.")
    if _last(stream, "select_columns"):
        # A choice of columns from a choice of columns is the second one alone (and as valid).
        kept = {name: stream.columns[name] for name in names}
        return Stream(stream.base, [*stream.steps[:-1], {"step_type": "select_columns", "config": {"columns": names}}],
                      kept, [*stream.lines[:-1], line])
    return stream.then({"step_type": "select_columns", "config": {"columns": names}}, line)


def rename(stream: Stream, mapping: dict[str, str], line: str) -> Stream:
    mapping = {old: new for old, new in mapping.items() if old != new}
    if not mapping:
        return stream
    if _last(stream, "rename_columns"):
        # Two renames in a row are one: each column from its first name to its last.
        before = _without_last(stream)
        first = stream.steps[-1]["config"]["mappings"]
        combined = {old: mapping.get(new, new) for old, new in first.items()}
        combined.update({old: new for old, new in mapping.items() if old not in first.values()})
        combined = {old: new for old, new in combined.items() if old != new}
        columns = {mapping.get(name, name): kind for name, kind in stream.columns.items()}
        if not combined:
            return Stream(before.base, before.steps, columns, before.lines)
        return Stream(before.base, [*before.steps, {"step_type": "rename_columns", "config": {"mappings": combined}}],
                      columns, [*before.lines, line])
    return stream.then({"step_type": "rename_columns", "config": {"mappings": mapping}}, line)


def sort(stream: Stream, keys: list[tuple[str, bool, bool]], line: str) -> Stream:
    """Sort by (column, ascending, empty values first) keys."""
    for name, _, _ in keys:
        if name not in stream.columns:
            raise NotConverted(f"It sorts by {name}, which the rows coming in do not have.")
    firsts = {first for _, _, first in keys}
    if len(firsts) == 1:
        return stream.then({"step_type": "sort_rows", "config": {
            "columns": [k for k, _, _ in keys], "ascending": [a for _, a, _ in keys],
            "na_position": "first" if firsts.pop() else "last"}}, line)
    # Each key with its own place for empty values: the SQL step says so per key.
    order = ", ".join(f"{_sql_name(k)} {'ASC' if a else 'DESC'} NULLS {'FIRST' if f else 'LAST'}" for k, a, f in keys)
    return sql(stream, f"SELECT * FROM input ORDER BY {order}", line)


def aggregate(stream: Stream, group_by: list[str], aggregations: list[tuple[str, str, str]], line: str) -> Stream:
    """Group, with (output name, function, column) aggregations."""
    return stream.then({"step_type": "aggregate", "config": {
        "group_by": group_by,
        "aggregations": [{"column": column, "function": function, "alias": alias}
                         for alias, function, column in aggregations]}}, line)


def distinct(stream: Stream, subset: list[str], line: str, *, keep: str = "first") -> Stream:
    """Remove repeated rows: by these columns, or by every column when none are named."""
    config: dict[str, Any] = {"keep": keep}
    if subset:
        config["subset"] = subset
    return stream.then({"step_type": "remove_duplicates", "config": config}, line)


def limit(stream: Stream, count: int, line: str) -> Stream:
    return stream.then({"step_type": "limit_rows", "config": {"count": count}}, line)


def sql(stream: Stream, text: str, line: str) -> Stream:
    return stream.then({"step_type": "tool", "config": {"tool": "code.sql", "sql": text}}, line)


def join(stream: Stream, other: str, other_columns: dict[str, PWType], *, how: str, on: list[str],
         right_on: list[str], bring: list[str], suffix: str, line: str, empty_keys: str = "never match") -> Stream:
    """Join as SQL does (or with two empty keys matching): the other side is a dataset."""
    step = {"step_type": "tool", "config": {"tool": "join.sql", "right_dataset_id": {"$dataset": other}, "how": how,
                                            "on": on, "right_on": right_on, "bring": bring, "suffix": suffix,
                                            "empty_keys": empty_keys}}
    columns = _compiled_columns(stream.columns, step)
    for name in bring:
        out = name if name not in stream.columns else f"{name}{suffix}"
        columns[out] = other_columns.get(name, UNKNOWN)
    return stream.then(step, line, columns=columns)


def union(stream: Stream, other: str, *, deduplicate: bool, line: str) -> Stream:
    step = {"step_type": "union_datasets", "config": {"other_dataset_id": {"$dataset": other},
                                                      "deduplicate": deduplicate, "column_strategy": "strict"}}
    return stream.then(step, line, columns=dict(stream.columns))


def _sql_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------- flow

Build = Callable[["Flow", dict[str, Stream]], dict[str, "Stream | Callable[[], Stream]"]]


@dataclass
class Component:
    id: str
    label: str
    #: input port -> (component id, its output port)
    inputs: dict[str, tuple[str, str]]
    build: Build | None
    section: Section
    #: For an output: the name of what it writes.
    writes: str | None = None


class Blocked(Exception):
    """A component that cannot be converted because one before it was not."""

    def __init__(self, reason: str, partial: Stream | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.partial = partial


class Flow:
    def __init__(self, conversion: Conversion, owner: str, key_prefix: str) -> None:
        self.conversion = conversion
        self.owner = owner
        self.key_prefix = key_prefix
        self.components: dict[str, Component] = {}
        self._streams: dict[str, dict[str, Stream]] = {}
        self._failed: dict[str, Blocked] = {}
        self._made: dict[int, tuple[str, dict[str, PWType]]] = {}

    def add(self, component: Component) -> Component:
        self.components[component.id] = component
        return component

    def stream(self, component_id: str, port: str) -> Stream:
        """The rows a component gives on a port, converting it (and what feeds it) once."""
        outputs = self._built(component_id)
        if port not in outputs:
            raise Blocked(f"{self.components[component_id].label} gives nothing on its {port} output here.", None)
        if callable(outputs[port]):
            # An output worked out only when something reads it.
            outputs[port] = outputs[port]()
        return outputs[port]

    def _built(self, component_id: str) -> dict[str, Any]:
        """Every output of a component, converting it (and what feeds it) once."""
        if component_id in self._failed:
            raise self._failed[component_id]
        if component_id not in self._streams:
            component = self.components.get(component_id)
            if component is None:
                raise Blocked("It is connected to a component that is not in the file.", None)
            inputs: dict[str, Stream] = {}
            for name, (source, source_port) in component.inputs.items():
                try:
                    inputs[name] = self.stream(source, source_port)
                except Blocked as exc:
                    label = self.components[source].label if source in self.components else source
                    blocked = Blocked(f"It follows {label}, which did not convert.", exc.partial)
                    self._failed[component_id] = blocked
                    component.section.not_converted(component.label, blocked.reason)
                    raise blocked from exc
            recipes_before, made_before = len(self.conversion.recipes), dict(self._made)
            try:
                if component.build is None:
                    raise NotConverted("It has nothing to convert.")
                self._streams[component_id] = component.build(self, inputs)
            except NotConverted as exc:
                # What it made on the way (a recipe for its other input) goes with it.
                del self.conversion.recipes[recipes_before:]
                self._made = made_before
                partial = next(iter(inputs.values()), None)
                self._failed[component_id] = Blocked(exc.reason, partial)
                component.section.not_converted(component.label, exc.reason)
                raise self._failed[component_id] from exc
        return self._streams[component_id]

    def labelled(self, label: str) -> Component:
        return next(component for component in self.components.values() if component.label == label)

    def converted(self, component: Component, lines: list[str] | str, notes: list[str] | None = None) -> None:
        component.section.converted(component.label, lines, notes)

    def dataset(self, stream: Stream, name: str) -> tuple[str, dict[str, PWType]]:
        """A dataset holding a stream: its dataset itself, or a recipe of its steps."""
        if not stream.steps:
            return stream.base, dict(stream.columns)
        key = id(stream)
        if key not in self._made:
            helper_key = f"{self.key_prefix}·{len(self._made) + 1}"
            recipe = RecipePlan(key=helper_key, name=f"{self.owner} · {name}"[:160], reads=stream.base,
                                steps=stream.steps, columns=stream.columns,
                                description=f"Made from {self.owner}: the rows {name} reads as its other input.")
            self.conversion.recipes.append(recipe)
            self._made[key] = (helper_key, dict(stream.columns))
        return self._made[key]

    def outputs(self) -> None:
        """A recipe for every output, in the file's order."""
        for component in self.components.values():
            if component.writes is None:
                continue
            if not component.inputs:
                component.section.not_converted(component.label, "Nothing is connected to it.")
                continue
            source, source_port = next(iter(component.inputs.values()))
            key = f"{self.key_prefix}:{component.id}"
            try:
                if component.build is not None:
                    # An output that shapes what it writes (a target's fields) is built itself.
                    stream = self.stream(component.id, next(iter(self._built(component.id))))
                else:
                    stream = self.stream(source, source_port)
            except Blocked as exc:
                if not any(entry.subject == component.label for entry in component.section.entries):
                    component.section.not_converted(component.label, exc.reason)
                if exc.partial is not None and exc.partial.steps:
                    self.conversion.recipes.append(RecipePlan(
                        key=key, name=component.writes[:160], reads=exc.partial.base, steps=exc.partial.steps,
                        columns=exc.partial.columns, complete=False,
                        description=f"Converted from {self.owner} as far as it goes: {exc.reason}"))
                    component.section.entries[-1].became.append(
                        f"The recipe “{component.writes}”, as a draft, with the {len(exc.partial.steps)} steps "
                        "before it")
                continue
            if not stream.steps:
                stream = sql(stream, "SELECT * FROM input", "Keep the rows as they are")
            self.conversion.recipes.append(RecipePlan(
                key=key, name=component.writes[:160], reads=stream.base, steps=stream.steps, columns=stream.columns,
                description=f"Converted from {self.owner}: what {component.label} writes."))
            component.section.converted(component.label, [f"The recipe “{component.writes}”, step {index}: {line}"
                                                          for index, line in enumerate(stream.lines, start=1)])

    def unused(self) -> None:
        """Components nothing reads and that write nothing: said, not left out silently."""
        used = {source for component in self.components.values() for source, _ in component.inputs.values()}
        for component in self.components.values():
            if component.writes is None and component.id not in used and component.id not in self._failed and \
                    not component.section.entries:
                if component.build is not None:
                    try:
                        # Built anyway, so one that would not convert says why.
                        self._built(component.id)
                    except Blocked:
                        continue
                    if component.section.entries:
                        component.section.entries.clear()
                component.section.nothing_to_do(component.label, "Nothing reads what it gives, so it makes no "
                                                                 "difference to any output.")

