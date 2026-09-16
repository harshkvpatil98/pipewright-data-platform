"""Nested and semi-structured data.

Phase 11's concrete answer to "every source will have a different set of
transformations". A JSON or XML source arrives with shapes a tabular source
never has -- an object inside a cell, an array of three line items, a document
that is really three related tables -- and the operations that deal with them
have no equivalent in the relational algebra.

So every tool here is an `Extension`: honestly outside the algebra, never
pushed to a source, with a handler that says exactly what it does to the
schema. That is the Phase 08 rule working as intended -- a step that resists
modelling is still expressible, and the cost is that nothing above it pushes
down, which is true rather than convenient.

The one judgement running through all of them: **an operation that changes what
a row means is never automatic**. `explode` turns one order into three line
items, and a row count that silently triples is how a total stops matching. The
reader keeps arrays as JSON text; turning them into rows is something somebody
asks for, here, where they can see it happen.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import JSON as JSON_TYPE
from shared_python.types import PWType, STRING

from service_transformations.ir.nodes import Extension, Node, freeze_config
from service_transformations.ir.pandas_backend import register_extension
from service_transformations.tools.declare import Example, Param, ParamKind, frame

CATEGORY = "Nested data"

#: How deep `flatten` will go. A recursive document would otherwise produce
#: thousands of columns from one record.
MAX_DEPTH = 6

#: Separator between the levels of a flattened path. Matches the ingestion
#: reader's, so `address.city` means the same thing whether it arrived
#: flattened or was flattened here.
SEPARATOR = "."


# ----------------------------------------------------------------- helpers


def _parse(value: Any) -> Any:
    """A cell as a document, whether it arrived as text or as an object.

    Columns coming from the JSON reader hold JSON *text*, because a frame cell
    holding a list compares unequal to itself and breaks deduplication. Columns
    produced mid-pipeline may hold the real object. Both have to work.
    """
    if value is None or isinstance(value, (list, dict)):
        return value
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _dump(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    return value


def _require(node: Node, column: str) -> None:
    if column not in node.schema():
        raise BadRequestError(
            f"There is no column called {column!r}. "
            f"This step has: {', '.join(node.schema()) or 'no columns'}."
        )


def _extension(node: Node, name: str, config: dict[str, Any], schema: dict[str, PWType] | None) -> Node:
    return Extension(
        input=node,
        name=name,
        config=freeze_config(config),
        output_schema=tuple(schema.items()) if schema is not None else None,
    )


# ------------------------------------------------------------- flatten


def _flatten_document(
    document: Any, prefix: str = "", depth: int = 0, out: dict[str, Any] | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {} if out is None else out
    if not isinstance(document, dict):
        row[prefix or "value"] = _dump(document)
        return row
    for key, value in document.items():
        name = f"{prefix}{SEPARATOR}{key}" if prefix else str(key)
        if isinstance(value, dict) and depth < MAX_DEPTH:
            nested = _flatten_document(value, name, depth + 1, row)
            if not nested:
                row[name] = None
        else:
            row[name] = _dump(value)
    return row


def _targets(column: str, fields: list[str], prefix: str, existing: list[str]) -> dict[str, str]:
    """Where each field path lands, avoiding collisions with real columns."""
    mapping: dict[str, str] = {}
    for path in fields:
        target = f"{prefix}{path}" if prefix else path
        # A flattened field that collides with an existing column would
        # overwrite it, which loses data and is never what anybody meant.
        if target in existing and target != column:
            target = f"{column}{SEPARATOR}{path}"
        mapping[path] = target
    return mapping


def _flatten_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = str(config["column"])
    fields = [str(name) for name in config["fields"]]
    drop = bool(config.get("drop_source", True))
    out = frame_in.copy()

    expanded = [_flatten_document(_parse(value) or {}) for value in out[column]]
    mapping = _targets(column, fields, str(config.get("prefix") or ""), list(out.columns))
    for path, target in mapping.items():
        # A path absent from a document is null for that row, which is what a
        # missing key means -- not an error, and not a reason to drop the row.
        out[target] = [row.get(path) for row in expanded]

    if drop and column in out.columns:
        out = out.drop(columns=[column])
    return out


def _flatten_build(node: Node, params: dict[str, Any]) -> Node:
    column = str(params["column"])
    _require(node, column)
    fields = [str(name) for name in params["fields"]]
    if not fields:
        # Required rather than discovered from the data, deliberately. A tool
        # whose output columns depend on the rows cannot be predicted by
        # lineage, and lineage that quietly reports the wrong columns is worse
        # than a tool that asks. Run "Describe a JSON column's shape" first --
        # it exists to produce exactly this list.
        raise BadRequestError(
            "Name the fields to flatten. Run 'Describe a JSON column's shape' on "
            f"{column!r} first to see what paths it holds."
        )

    schema = dict(node.schema())
    mapping = _targets(column, fields, str(params["prefix"] or ""), list(schema))
    if params["drop_source"]:
        schema.pop(column, None)
    for target in mapping.values():
        schema[target] = STRING
    return _extension(
        node,
        "nested.flatten",
        {
            "column": column,
            "fields": fields,
            "drop_source": params["drop_source"],
            "prefix": params["prefix"],
        },
        schema,
    )


register_extension("nested.flatten", _flatten_handler)

frame("nested.flatten", "Flatten object into columns", CATEGORY,
      "Turn a column holding an object into one column per field, named by their path.",
      _flatten_build,
      synonyms=("unnest object", "expand object", "json to columns", "normalize object"),
      params=(
          Param("column", "Column", ParamKind.COLUMN),
          Param("fields", "Fields", ParamKind.COLUMNS,
                help="Dotted paths, e.g. address.city. Use 'Describe a JSON column's "
                     "shape' to list what is there."),
          Param("prefix", "Prefix", ParamKind.TEXT, required=False, default=""),
          Param("drop_source", "Remove the original column", ParamKind.BOOLEAN,
                required=False, default=True),
      ),
      example=Example(
          rows=({"id": 1, "who": '{"name": "Ada", "address": {"city": "London"}}'},),
          params={"fields": ["name", "address.city"], "drop_source": True},
          column="who",
          output="address.city",
          expect=("London",),
          note="Nested objects keep their path, so `address.city` is one column.",
      ))


# ------------------------------------------------------------- explode


def _explode_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = str(config["column"])
    keep_empty = bool(config.get("keep_empty", True))

    out = frame_in.copy()
    out[column] = [
        parsed if isinstance(parsed := _parse(value), list) else ([] if parsed is None else [parsed])
        for value in out[column]
    ]
    if keep_empty:
        # An order with no line items is still an order. Dropping it makes a
        # left join of the exploded table lose rows nobody knows are missing.
        out[column] = out[column].map(lambda items: items if items else [None])
    out = out.explode(column, ignore_index=True)
    # Elements come out as text, uniformly. A JSON array is routinely mixed --
    # `[1, "n/a", 3]` -- so there is no one type to give the column, and the
    # declared schema says STRING. Producing ints here and text there would
    # make the declared type a lie in half the files.
    out[column] = out[column].map(
        lambda value: None if value is None else _dump(value)
        if isinstance(value, (list, dict))
        else str(value)
    )
    return out


def _explode_build(node: Node, params: dict[str, Any]) -> Node:
    column = str(params["column"])
    _require(node, column)
    schema = dict(node.schema())
    # The column survives with one element per row; everything else is
    # unchanged. The row *count* changes, which no schema can express -- which
    # is exactly why this is a step somebody chooses rather than a default.
    schema[column] = STRING
    return _extension(
        node,
        "nested.explode",
        {"column": column, "keep_empty": params["keep_empty"]},
        schema,
    )


register_extension("nested.explode", _explode_handler)

frame("nested.explode", "Explode array into rows", CATEGORY,
      "Turn a column holding an array into one row per element, repeating the other columns.",
      _explode_build,
      synonyms=("unnest array", "array to rows", "expand rows", "flatten array"),
      params=(
          Param("column", "Column", ParamKind.COLUMN),
          Param("keep_empty", "Keep rows with an empty array", ParamKind.BOOLEAN,
                required=False, default=True),
      ),
      example=Example(
          rows=({"order": "A", "items": "[1, 2, 3]"},),
          column="items",
          output="items",
          expect=("1", "2", "3"),
          note="One row becomes three. Every other column repeats.",
      ))


# --------------------------------------------------------- json_extract


def _walk(document: Any, path: str) -> Any:
    """Follow a dotted path, stepping into arrays by index."""
    current = document
    for part in path.split(SEPARATOR):
        part = part.strip()
        if not part:
            continue
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _extract_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = str(config["column"])
    path = str(config["path"])
    into = str(config["into"])
    out = frame_in.copy()
    out[into] = [_dump(_walk(_parse(value), path)) for value in out[column]]
    return out


def _extract_build(node: Node, params: dict[str, Any]) -> Node:
    column = str(params["column"])
    _require(node, column)
    into = str(params["into"] or f"{column}_{params['path'].replace(SEPARATOR, '_')}")
    schema = dict(node.schema())
    # STRING rather than the value's real type: a path can select a number in
    # one row and a string in the next, and claiming a type the data does not
    # keep is worse than being honest that this needs a cast afterwards.
    schema[into] = STRING
    return _extension(
        node,
        "nested.json_extract",
        {"column": column, "path": params["path"], "into": into},
        schema,
    )


register_extension("nested.json_extract", _extract_handler)

frame("nested.json_extract", "Extract a value by path", CATEGORY,
      "Pull one value out of a JSON column by its dotted path, e.g. `address.city` "
      "or `items.0.sku`.",
      _extract_build,
      synonyms=("json path", "jsonpath", "get nested value", "pluck"),
      params=(
          Param("column", "Column", ParamKind.COLUMN),
          Param("path", "Path", ParamKind.TEXT),
          Param("into", "New column", ParamKind.TEXT, required=False, default=""),
      ),
      example=Example(
          rows=({"payload": '{"address": {"city": "Oslo"}}'},),
          params={"column": "payload", "path": "address.city", "into": "city"},
          output="city",
          expect=("Oslo",),
      ))


# -------------------------------------------------------------- collect


def _collect_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    keys = [str(name) for name in config["group_by"]]
    column = str(config["column"])
    into = str(config["into"])
    missing = [name for name in keys + [column] if name not in frame_in.columns]
    if missing:
        raise BadRequestError(f"No column(s) called: {', '.join(missing)}.")

    def _gather(values: pd.Series) -> Any:
        kept = [_dump(value) for value in values if not pd.isna(value)]
        # A group with no values at all is null rather than `[]`. An empty
        # array reads as "we looked and there were none", which is a different
        # claim from "there was nothing here to look at".
        return json.dumps(kept, default=str) if kept else None

    if frame_in.empty:
        return pd.DataFrame(columns=[*keys, into])

    grouped = frame_in.groupby(keys, dropna=False)[column].apply(_gather).reset_index()
    return grouped.rename(columns={column: into})


def _collect_build(node: Node, params: dict[str, Any]) -> Node:
    keys = [str(name) for name in params["group_by"]]
    column = str(params["column"])
    for name in [*keys, column]:
        _require(node, name)
    into = str(params["into"] or f"{column}_list")
    existing = node.schema()
    schema = {name: existing[name] for name in keys}
    schema[into] = JSON_TYPE
    return _extension(
        node,
        "nested.collect",
        {"group_by": keys, "column": column, "into": into},
        schema,
    )


register_extension("nested.collect", _collect_handler)

frame("nested.collect", "Collect rows into an array", CATEGORY,
      "The inverse of explode: gather a column's values into one array per group.",
      _collect_build,
      synonyms=("group into array", "array_agg", "implode", "nest", "unexplode"),
      params=(
          Param("group_by", "Group by", ParamKind.COLUMNS),
          Param("column", "Collect", ParamKind.COLUMN),
          Param("into", "New column", ParamKind.TEXT, required=False, default=""),
      ),
      example=Example(
          rows=(
              {"order": "A", "sku": "x"},
              {"order": "A", "sku": "y"},
              {"order": "B", "sku": "z"},
          ),
          params={"group_by": ["order"], "into": "skus"},
          column="sku",
          output="skus",
          expect=('["x", "y"]', '["z"]'),
      ))


# ----------------------------------------------------- infer_json_schema


def _describe(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _shape(document: Any, prefix: str = "", out: dict[str, set[str]] | None = None, depth: int = 0) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {} if out is None else out
    if isinstance(document, dict) and depth < MAX_DEPTH:
        for key, value in document.items():
            name = f"{prefix}{SEPARATOR}{key}" if prefix else str(key)
            found.setdefault(name, set()).add(_describe(value))
            if isinstance(value, dict):
                _shape(value, name, found, depth + 1)
            elif isinstance(value, list) and value:
                _shape(value[0], f"{name}[]", found, depth + 1)
    elif prefix:
        found.setdefault(prefix, set()).add(_describe(document))
    return found


def _infer_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = str(config["column"])
    shape: dict[str, set[str]] = {}
    present: dict[str, int] = {}
    total = 0
    for value in frame_in[column]:
        document = _parse(value)
        if document is None:
            continue
        total += 1
        for path, kinds in _shape(document).items():
            shape.setdefault(path, set()).update(kinds)
            present[path] = present.get(path, 0) + 1

    rows = [
        {
            "path": path,
            "types": ", ".join(sorted(kinds)),
            "present_in": present.get(path, 0),
            "of_documents": total,
            # The number that matters: a field in 3% of documents is optional,
            # and a pipeline built on it breaks on the other 97%.
            "always_present": present.get(path, 0) == total and total > 0,
        }
        for path, kinds in sorted(shape.items())
    ]
    # No documents means no fields. Returning a placeholder row would be
    # inventing a finding from an empty table.
    return pd.DataFrame(
        rows, columns=["path", "types", "present_in", "of_documents", "always_present"]
    )


def _infer_build(node: Node, params: dict[str, Any]) -> Node:
    column = str(params["column"])
    _require(node, column)
    from shared_python.types import BOOLEAN, INT64

    return _extension(
        node,
        "nested.infer_json_schema",
        {"column": column},
        {
            "path": STRING,
            "types": STRING,
            "present_in": INT64,
            "of_documents": INT64,
            "always_present": BOOLEAN,
        },
    )


register_extension("nested.infer_json_schema", _infer_handler)

frame("nested.infer_json_schema", "Describe a JSON column's shape", CATEGORY,
      "Replace the table with one row per field found in a JSON column: its path, "
      "the types seen there, and how many documents actually have it.",
      _infer_build,
      synonyms=("json schema", "describe json", "what is in this column", "shape"),
      params=(Param("column", "Column", ParamKind.COLUMN),),
      example=Example(
          rows=(
              {"payload": '{"id": 1, "tags": ["a"]}'},
              {"payload": '{"id": 2}'},
          ),
          output="path",
          expect=("id", "tags", "tags[]"),
          note="`id` is in both documents and `tags` is in one, which is the useful "
               "part: a pipeline built on `tags` breaks on half the rows. `tags[]` "
               "describes what is inside the array.",
      ))


# ------------------------------------------------------------ normalise


def _child_columns(key: str, prefix: str, fields: list[str]) -> list[str]:
    """The child table's columns: the parent key, the position, then the fields."""
    return [key, f"{prefix}index", *[f"{prefix}{path}" if prefix else path for path in fields]]


def _normalise_handler(frame_in: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = str(config["column"])
    key = str(config["key"])
    prefix = str(config.get("child_prefix") or "")
    fields = [str(name) for name in config["fields"]]

    if key not in frame_in.columns:
        raise BadRequestError(
            f"There is no column called {key!r} to use as the parent key. "
            "A child table needs a key back to its parent, or the rows cannot be rejoined."
        )

    columns = _child_columns(key, prefix, fields)
    rows: list[dict[str, Any]] = []
    for parent_key, value in zip(frame_in[key], frame_in[column]):
        document = _parse(value)
        items = document if isinstance(document, list) else ([] if document is None else [document])
        for position, item in enumerate(items):
            flat = _flatten_document(item if isinstance(item, dict) else {"value": item})
            row = {key: parent_key, f"{prefix}index": position}
            for path in fields:
                row[f"{prefix}{path}" if prefix else path] = flat.get(path)
            rows.append(row)

    # An empty child table still has to have its columns, or the join back to
    # the parent fails with a confusing error rather than returning no rows.
    return pd.DataFrame(rows, columns=columns)


def _normalise_build(node: Node, params: dict[str, Any]) -> Node:
    column = str(params["column"])
    key = str(params["key"])
    _require(node, column)
    _require(node, key)
    fields = [str(name) for name in params["fields"]]
    if not fields:
        raise BadRequestError(
            "Name the fields each child row should carry. Run 'Describe a JSON "
            f"column's shape' on {column!r} first to see what paths it holds."
        )
    prefix = str(params["child_prefix"] or "")

    from shared_python.types import INT64

    existing = node.schema()
    schema: dict[str, PWType] = {key: existing[key], f"{prefix}index": INT64}
    for path in fields:
        schema[f"{prefix}{path}" if prefix else path] = STRING
    return _extension(
        node,
        "nested.normalise",
        {"column": column, "key": key, "child_prefix": prefix, "fields": fields},
        schema,
    )


register_extension("nested.normalise", _normalise_handler)

frame("nested.normalise", "Split a nested array into its own table", CATEGORY,
      "Turn one document with a repeated section into a child table, carrying the "
      "parent's key so the two can be joined back together.",
      _normalise_build,
      synonyms=("child table", "split out", "one to many", "relational", "shred"),
      params=(
          Param("column", "Nested column", ParamKind.COLUMN),
          Param("key", "Parent key", ParamKind.COLUMN),
          Param("fields", "Fields to keep", ParamKind.COLUMNS,
                help="Dotted paths inside each element, e.g. sku or product.name."),
          Param("child_prefix", "Child column prefix", ParamKind.TEXT,
                required=False, default=""),
      ),
      example=Example(
          rows=({"order_id": "A", "lines": '[{"sku": "x", "qty": 2}]'},),
          params={"key": "order_id", "fields": ["sku", "qty"]},
          column="lines",
          output="sku",
          expect=("x",),
          note="The result is the child table. `order_id` travels with it so a "
               "join puts the two back together.",
      ))
