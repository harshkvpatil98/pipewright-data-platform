"""Helpers for tools that run here: an `Extension` node and its pandas handler.

A tool the algebra cannot express (a fuzzy join, a forecast, a sample) is
still IR: an `Extension` that says what it produces, so lineage and the steps
after it know its columns, and that never pushes down. The handler is
registered with the pandas backend under the tool's name and is given the
frame and the tool's settings.

A tool that reads another dataset saves it as `right_dataset_id`, the key
bundles, promotion, lineage, previews, runs and the kept-results cache follow,
and reads it through the step's context, under the reader's policies like a
join step does.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import PWType
from shared_python.types.lattice import UNKNOWN

from service_transformations.ir.nodes import Extension, Node, freeze_config
from service_transformations.ir.pandas_backend import register_extension
from service_transformations.steps.context import active_context

Handler = Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]


def extension(node: Node, name: str, config: dict[str, Any], schema: dict[str, PWType] | None) -> Extension:
    return Extension(input=node, name=name, config=freeze_config(config),
                     output_schema=tuple(schema.items()) if schema is not None else None)


def handles(name: str) -> Callable[[Handler], Handler]:
    """Register a function as the pandas handler of a tool's Extension."""

    def register(handler: Handler) -> Handler:
        register_extension(name, handler)
        return handler

    return register


def columns_of(node: Node, names: list[str] | tuple[str, ...] | None, label: str) -> list[str]:
    available = node.schema()
    missing = [name for name in names or [] if name not in available]
    if missing:
        raise BadRequestError(
            f"{label}: {', '.join(repr(m) for m in missing)} {'is' if len(missing) == 1 else 'are'} not in this "
            f"dataset. Available: {', '.join(available) or 'none'}."
        )
    return list(names or [])


def other_dataset(config: dict[str, Any]) -> pd.DataFrame:
    """The dataset a tool reads, as the reader may see it."""
    dataset_id = config.get("right_dataset_id")
    if not dataset_id:
        raise BadRequestError("Choose the dataset to read.")
    return active_context().load_dataset(str(dataset_id))


def other_label(config: dict[str, Any]) -> str:
    return active_context().dataset_label(str(config.get("right_dataset_id")))


def require_other_columns(frame: pd.DataFrame, names: list[str], label: str, config: dict[str, Any]) -> None:
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise BadRequestError(
            f"{label}: {other_label(config)} has no {', '.join(repr(m) for m in missing)}. "
            f"It has: {', '.join(map(str, frame.columns)) or 'no columns'}."
        )


def brought(node: Node, bring: list[str], *, suffix: str = "_right", extra: dict[str, PWType] | None = None,
            ) -> dict[str, PWType]:
    """This dataset's columns, then the other's brought ones (suffixed when a name is taken)."""
    schema = dict(node.schema())
    for name in bring:
        schema[name if name not in node.schema() else f"{name}{suffix}"] = UNKNOWN
    for name, type_ in (extra or {}).items():
        if name in schema:
            raise BadRequestError(f"Column {name!r} already exists. Choose another name.")
        schema[name] = type_
    return schema


def rename_brought(frame: pd.DataFrame, left: pd.DataFrame, bring: list[str], suffix: str) -> pd.DataFrame:
    return frame.rename(columns={name: f"{name}{suffix}" for name in bring if name in left.columns})


def column_extension(name: str, result_type: PWType | None, values: Callable[[pd.Series, dict[str, Any]], Any],
                     *, keys: tuple[str, ...] = (), frame_aware: bool = False, fills: bool = False):
    """A column tool that runs here: one input column to one output column.

    ``values(series, config)`` gives the new values (or, with ``frame_aware``,
    ``values(frame, config)``). An empty value in stays empty out without the
    function seeing it, the rule every tool keeps. ``result_type`` None keeps
    the column's own type.
    """
    from service_transformations.tools.builders import require_column

    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        into = (params.get("into") or "").strip() or column
        schema = dict(node.schema())
        if into != column and into in schema:
            raise BadRequestError(f"Column {into!r} already exists. Choose another name, or leave the "
                                  "destination empty to replace the original.")
        schema[into] = result_type if result_type is not None else schema[column]
        config = {"column": column, "into": into, **{key: params.get(key) for key in keys}}
        return extension(node, name, config, schema)

    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        out = frame.copy()
        source = frame[config["column"]]
        produced = values(frame if frame_aware else source, config)
        produced = pd.Series(list(produced) if not isinstance(produced, pd.Series) else produced.tolist(),
                             index=frame.index, dtype=object)
        if not fills:
            produced[source.isna().to_numpy()] = None
        out[config["into"]] = produced.infer_objects()
        return out

    register_extension(name, handler)
    return build


def each(fn: Callable[[Any], Any]) -> Callable[[pd.Series, dict[str, Any]], list[Any]]:
    """Apply ``fn`` to each present value; empty stays empty."""

    def run(series: pd.Series, _config: dict[str, Any]) -> list[Any]:
        return [None if pd.isna(value) else fn(value) for value in series]

    return run
