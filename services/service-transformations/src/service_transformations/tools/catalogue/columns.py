"""Column structure tools.

These reshape the frame rather than one column's values, so they build their own
IR rather than going through the per-column helper.
"""

from __future__ import annotations

import re

from shared_python.errors import BadRequestError

from service_transformations.ir.expressions import Column, Expr
from service_transformations.ir.nodes import Node, Project
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.declare import Example, Param, ParamKind, frame

CATEGORY = "Columns"


def _project(node: Node, names: list[str], expressions: dict[str, Expr] | None = None) -> Project:
    lookup = expressions or {}
    return Project(
        input=node,
        projections=tuple((name, lookup.get(name, Column(name))) for name in names),
    )


def _reorder(node: Node, params: dict) -> Node:
    """Move named columns to the front or back, keeping everything else in order."""
    schema = list(node.schema())
    moving = [name for name in params["columns"] if name in schema]
    unknown = [name for name in params["columns"] if name not in schema]
    if unknown:
        raise BadRequestError(f"Not in this dataset: {', '.join(unknown)}.")
    rest = [name for name in schema if name not in moving]
    ordered = moving + rest if params["position"] == "start" else rest + moving
    return _project(node, ordered)


frame("columns.move", "Move columns", CATEGORY,
      "Move columns to the start or the end, leaving the rest in order.",
      _reorder,
      synonyms=("reorder", "move to front", "move to end", "arrange"),
      params=(
          Param("columns", "Columns", ParamKind.COLUMNS),
          Param("position", "Move to", ParamKind.SELECT, default="start",
                options=("start", "end")),
      ),
      example=Example(
          rows=({"a": 1, "b": 2, "c": 3},),
          params={"columns": ["c"], "position": "start"},
          output="__columns__",
          expect=("c,a,b",),
      ))


def _sort_columns(node: Node, params: dict) -> Node:
    names = sorted(node.schema(), reverse=params["descending"])
    return _project(node, names)


frame("columns.sort", "Sort columns by name", CATEGORY,
      "Put the columns in alphabetical order.", _sort_columns,
      synonyms=("alphabetical", "order columns"),
      params=(Param("descending", "Reverse", ParamKind.BOOLEAN, required=False, default=False),),
      example=Example(
          rows=({"c": 1, "a": 2, "b": 3},),
          params={"descending": False},
          output="__columns__",
          expect=("a,b,c",),
      ))


def _keep_only(node: Node, params: dict) -> Node:
    schema = list(node.schema())
    keep = [name for name in schema if name in set(params["columns"])]
    if not keep:
        raise BadRequestError("Keeping no columns would leave an empty dataset.")
    return _project(node, keep)


frame("columns.keep_only", "Keep only these columns", CATEGORY,
      "Drop everything else, in the dataset's own order.", _keep_only,
      synonyms=("select", "subset", "choose columns"),
      params=(Param("columns", "Columns to keep", ParamKind.COLUMNS),),
      example=Example(
          rows=({"a": 1, "b": 2, "c": 3},),
          params={"columns": ["a", "c"]},
          output="__columns__",
          expect=("a,c",),
      ))


def _drop(node: Node, params: dict) -> Node:
    schema = list(node.schema())
    dropping = set(params["columns"])
    unknown = sorted(dropping - set(schema))
    if unknown:
        raise BadRequestError(f"Not in this dataset: {', '.join(unknown)}.")
    remaining = [name for name in schema if name not in dropping]
    if not remaining:
        raise BadRequestError("Dropping every column would leave an empty dataset.")
    return _project(node, remaining)


frame("columns.drop", "Drop columns", CATEGORY, "Remove one or more columns.", _drop,
      synonyms=("remove columns", "delete columns"),
      params=(Param("columns", "Columns to drop", ParamKind.COLUMNS),),
      example=Example(
          rows=({"a": 1, "b": 2},),
          params={"columns": ["b"]},
          output="__columns__",
          expect=("a",),
      ))


def _duplicate(node: Node, params: dict) -> Node:
    source = require_column(node, params.get("column"))
    target = params.get("into") or unique_name(node, f"{source}_copy")
    names = [*node.schema(), target]
    return _project(node, names, {target: Column(source)})


frame("columns.duplicate", "Duplicate a column", CATEGORY,
      "Add a copy, so the original survives an experiment.", _duplicate,
      synonyms=("copy column", "clone"),
      params=(Param("column", "Column", ParamKind.COLUMN),),
      example=Example(
          rows=({"a": 1},),
          params={"column": "a"},
          output="a_copy",
          expect=(1,),
      ))


def _rename(node: Node, params: dict) -> Node:
    schema = list(node.schema())
    source = require_column(node, params["column"])
    target = params["new_name"].strip()
    if not target:
        raise BadRequestError("A rename needs a new name.")
    if target in schema and target != source:
        raise BadRequestError(f"There is already a column called {target!r}.")
    names = [target if name == source else name for name in schema]
    return Project(
        input=node,
        projections=tuple(
            (target if name == source else name, Column(name)) for name in schema
        ),
    ) if names else _project(node, names)


frame("columns.rename", "Rename a column", CATEGORY, "Give a column a new name.", _rename,
      synonyms=("rename",),
      params=(
          Param("column", "Column", ParamKind.COLUMN),
          Param("new_name", "New name", ParamKind.TEXT),
      ),
      example=Example(
          rows=({"a": 1},),
          params={"column": "a", "new_name": "b"},
          output="__columns__",
          expect=("b",),
      ))


def _bulk_rename(node: Node, params: dict) -> Node:
    schema = list(node.schema())
    style = params["style"]
    pattern = params["find"] or ""
    replacement = params["replace_with"] or ""

    def renamed(name: str) -> str:
        if style == "regex":
            try:
                return re.sub(pattern, replacement, name)
            except re.error as exc:
                raise BadRequestError(f"That pattern will not compile: {exc}") from exc
        if style == "prefix":
            return f"{replacement}{name}"
        if style == "suffix":
            return f"{name}{replacement}"
        if style == "snake_case":
            spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
            return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")
        if style == "lower":
            return name.lower()
        if style == "upper":
            return name.upper()
        return name.replace(pattern, replacement) if pattern else name

    mapping = [(name, renamed(name)) for name in schema]
    produced = [new for _, new in mapping]
    clashes = sorted({name for name in produced if produced.count(name) > 1})
    if clashes:
        raise BadRequestError(
            f"That would give more than one column the same name: {', '.join(clashes)}."
        )
    if any(not new.strip() for new in produced):
        raise BadRequestError("That would leave a column with no name.")
    return Project(input=node, projections=tuple((new, Column(old)) for old, new in mapping))


frame("columns.bulk_rename", "Rename many columns", CATEGORY,
      "Apply one renaming rule to every column at once.", _bulk_rename,
      synonyms=("rename all", "clean headers", "snake case", "prefix", "suffix"),
      params=(
          Param("style", "Rule", ParamKind.SELECT, default="snake_case",
                options=("snake_case", "lower", "upper", "prefix", "suffix", "replace", "regex")),
          Param("find", "Find", ParamKind.TEXT, required=False, default=""),
          Param("replace_with", "Replace with", ParamKind.TEXT, required=False, default=""),
      ),
      example=Example(
          rows=({"Order ID": 1, "customerName": 2},),
          params={"style": "snake_case", "find": "", "replace_with": ""},
          output="__columns__",
          expect=("order_id,customer_name",),
      ))
