"""Columns, rows and reshaping: the rest of the roadmap's structure tools (E1).

Where the algebra can say it, a tool is IR and pushes down (a constant
column, a split at fixed positions, a custom sort order, rows that fail to
convert). The rest (the last rows, a shuffle, headers from the first row, a
transpose) run here as extensions that say what they produce, or say that
their columns come from the data.
"""

from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, JSON as JSON_TYPE, STRING, PWType

from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr, Literal
from service_transformations.ir.nodes import Filter, Node, Project, Sort, SortKey
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import columns_of, extension, handles
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec


def _declare(name: str, title: str, category: str, summary: str, build, example: Example, *,
             params: tuple[Param, ...] = (), synonyms: tuple[str, ...] = (), column_scoped: bool = False,
             local_only: bool = False, accepts: Accepts = Accepts.ANY, null_answer: bool = False,
             dynamic_columns: bool = False, adds_rows: bool = False, row_wise: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, accepts=accepts, column_scoped=column_scoped, local_only=local_only,
        null_answer=null_answer, warns_lost=False, dynamic_columns=dynamic_columns, adds_rows=adds_rows,
        row_wise=row_wise,
    ))


def _passing(node: Node, **made: Expr) -> Project:
    return Project(node, tuple([(name, Column(name)) for name in node.schema()] + list(made.items())))


# ================================================================== columns

COLUMNS = "Columns"

_TYPES: dict[str, PWType] = {"text": STRING, "number": FLOAT64, "whole number": INT64, "true or false": BOOLEAN,
                             "date": DATE}


def _add(node: Node, params: dict[str, Any]) -> Node:
    name = (params.get("name") or "").strip()
    if not name:
        raise BadRequestError("Name the new column.")
    if name in node.schema():
        raise BadRequestError(f"Column {name!r} already exists. Choose another name.")
    kind = params.get("type") or "text"
    raw = params.get("value")
    if raw is None or raw == "":
        value: Expr = Literal(None, _TYPES[kind])
    elif kind == "text":
        value = Literal(str(raw), STRING)
    elif kind == "true or false":
        token = str(raw).strip().lower()
        if token not in ("true", "false", "yes", "no", "1", "0"):
            raise BadRequestError("A true or false value is true or false.")
        value = Literal(token in ("true", "yes", "1"), BOOLEAN)
    elif kind == "date":
        value = Cast(Literal(str(raw), STRING), DATE)
    else:
        try:
            number = float(raw)
        except ValueError:
            raise BadRequestError(f"{raw!r} is not a number.") from None
        value = Literal(int(number), INT64) if kind == "whole number" and number.is_integer() else Literal(number, FLOAT64)
        if kind == "whole number" and not number.is_integer():
            raise BadRequestError(f"{raw!r} is not a whole number.")
    return _passing(node, **{name: value})


_declare("columns.add", "Add a column with one value", COLUMNS, "Add a column holding the same value on every "
         "row: a source label, a default, a flag to fill in later.", _add,
         Example(rows=({"id": 1}, {"id": 2}), params={"name": "source", "value": "web"}, column="id",
                 output="source", expect=("web", "web")),
         params=(Param("name", "New column", ParamKind.TEXT),
                 Param("value", "Value", ParamKind.TEXT, required=False, default=""),
                 Param("type", "Kind of value", ParamKind.SELECT, required=False, default="text",
                       options=tuple(_TYPES))),
         synonyms=("add column", "new column", "constant column", "literal column", "insert column"),
         null_answer=True)


def _positions(raw: list[str]) -> list[int]:
    try:
        positions = sorted({int(item) for item in raw})
    except ValueError:
        raise BadRequestError("Positions are whole numbers: the characters before each cut.") from None
    if not positions or positions[0] < 1:
        raise BadRequestError("Cut after at least the first character.")
    return positions


def _split_positions(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    cuts = _positions(params["positions"])
    starts = [0, *cuts]
    made: dict[str, Expr] = {}
    for index, start in enumerate(starts, start=1):
        name = unique_name(node, f"{column}_{index}")
        length = (cuts[index - 1] - start) if index <= len(cuts) else None
        args: tuple[Expr, ...] = (Column(column), Literal(start + 1, INT64))
        if length is not None:
            args += (Literal(length, INT64),)
        made[name] = Call("substring", args)
    projections = [(name, Column(name)) for name in node.schema() if not (params.get("drop") and name == column)]
    return Project(node, tuple(projections + list(made.items())))


_declare("columns.split_by_position", "Split at fixed positions", COLUMNS, "Cut text into pieces after given "
         "numbers of characters (fixed-width records, codes with parts).", _split_positions,
         Example(rows=({"code": "GB12345"}, {"code": "FR9"}), params={"positions": ["2", "4"]}, column="code",
                 output="code_2", expect=("12", "9")),
         params=(Param("positions", "Cut after these characters", ParamKind.LIST, placeholder="2\n4"),
                 Param("drop", "Drop the original", ParamKind.BOOLEAN, required=False, default=False)),
         synonyms=("split by position", "fixed width", "split at character", "substring columns"),
         column_scoped=True, accepts=Accepts.TEXTUAL)


def _split_pattern_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    try:
        re.compile(params["pattern"])
    except re.error as exc:
        raise BadRequestError(f"That pattern will not compile: {exc}.") from None
    parts = int(params["parts"])
    schema = {name: type_ for name, type_ in node.schema().items() if not (params.get("drop") and name == column)}
    names = [unique_name(node, f"{column}_{index}") for index in range(1, parts + 1)]
    for name in names:
        schema[name] = STRING
    return extension(node, "columns.split_by_pattern",
                     {"column": column, "pattern": params["pattern"], "names": names, "drop": bool(params.get("drop"))},
                     schema)


@handles("columns.split_by_pattern")
def _split_pattern(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    names = list(config["names"])
    text = frame[config["column"]].map(lambda v: None if pd.isna(v) else str(v))
    pieces = text.map(lambda v: [] if v is None else re.split(config["pattern"], v, maxsplit=len(names) - 1))
    out = frame.drop(columns=[config["column"]]) if config.get("drop") else frame.copy()
    for index, name in enumerate(names):
        out[name] = [None if not row and text.iloc[i] is None else (row[index] if index < len(row) else None)
                     for i, row in enumerate(pieces)]
    return out


_declare("columns.split_by_pattern", "Split by a pattern", COLUMNS, "Split text into columns wherever a "
         "regular expression matches: any run of spaces, a dash or a slash, a comma with or without a space.",
         _split_pattern_build,
         Example(rows=({"v": "a - b/c"}, {"v": "d"}), params={"pattern": r"\s*[-/]\s*", "parts": 3}, column="v",
                 output="v_2", expect=("b", None)),
         params=(Param("pattern", "Pattern", ParamKind.TEXT, placeholder=r"\s*,\s*"),
                 Param("parts", "Most columns", ParamKind.INTEGER, default=2, minimum=1, maximum=100),
                 Param("drop", "Drop the original", ParamKind.BOOLEAN, required=False, default=False)),
         synonyms=("split by regex", "regex split", "split on pattern", "tokenise"),
         column_scoped=True, local_only=True, accepts=Accepts.TEXTUAL, row_wise=True)


def _split_rows_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    if not params.get("delimiter"):
        raise BadRequestError("Say what separates the values.")
    return extension(node, "columns.split_to_rows",
                     {"column": column, "into": column, "delimiter": params["delimiter"],
                      "trim": bool(params.get("trim", True))},
                     dict(node.schema()))


@handles("columns.split_to_rows")
def _split_rows(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column, delimiter = config["column"], config["delimiter"]
    trim = config.get("trim", True)

    def pieces(value: Any) -> list[Any]:
        if pd.isna(value):
            return [None]
        found = str(value).split(delimiter)
        found = [piece.strip() for piece in found] if trim else found
        return [piece for piece in found if piece != ""] or [None]

    out = frame.copy()
    out[column] = out[column].map(pieces)
    return out.explode(column, ignore_index=True)


_declare("columns.split_to_rows", "Split into rows", COLUMNS, "Give each value in a list (\"red, green, blue\") "
         "its own row, repeating the other columns.", _split_rows_build,
         Example(rows=({"id": 1, "tags": "red, green"}, {"id": 2, "tags": "blue"}), params={"delimiter": ","},
                 column="tags", output="tags", expect=("red", "green", "blue")),
         params=(Param("delimiter", "Separated by", ParamKind.TEXT, default=","),
                 Param("trim", "Trim spaces around each", ParamKind.BOOLEAN, required=False, default=True)),
         synonyms=("split to rows", "explode", "unnest", "one row per value", "split rows"),
         column_scoped=True, local_only=True, accepts=Accepts.TEXTUAL)


def _promote_build(node: Node, params: dict[str, Any]) -> Node:
    return extension(node, "columns.promote_headers", {}, None)


@handles("columns.promote_headers")
def _promote(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    names: list[str] = []
    for position, value in enumerate(frame.iloc[0].tolist(), start=1):
        name = "" if pd.isna(value) else str(value).strip()
        name = name or f"column_{position}"
        base, number = name, 2
        while name in names:
            name = f"{base}_{number}"
            number += 1
        names.append(name)
    out = frame.iloc[1:].reset_index(drop=True).copy()
    out.columns = names
    return out.infer_objects()


_declare("columns.promote_headers", "Use the first row as column names", COLUMNS, "Take the column names from "
         "the first row and drop it, for a file whose header was read as data. A blank name becomes column_N.",
         _promote_build,
         Example(rows=({"a": "name", "b": "age"}, {"a": "Ana", "b": "41"}), column="a", output="__columns__",
                 expect=("name,age",)),
         synonyms=("promote headers", "first row as header", "rename from first row", "header row", "use row 1"),
         local_only=True, dynamic_columns=True)


def _demote_build(node: Node, params: dict[str, Any]) -> Node:
    names = [f"column_{index}" for index in range(1, len(node.schema()) + 1)]
    return extension(node, "columns.demote_headers", {"names": names}, {name: STRING for name in names})


@handles("columns.demote_headers")
def _demote(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    names = list(config["names"])
    header = pd.DataFrame([[str(name) for name in frame.columns]], columns=names)
    body = frame.copy()
    body.columns = names
    body = body.astype(object).where(body.notna(), None).map(lambda v: None if v is None else str(v))
    return pd.concat([header, body], ignore_index=True)


_declare("columns.demote_headers", "Turn column names into the first row", COLUMNS, "Move the column names into "
         "a first row and name the columns column_1, column_2: for data that has to be read without a header.",
         _demote_build,
         Example(rows=({"name": "Ana"},), column="name", output="column_1", expect=("name", "Ana")),
         synonyms=("demote headers", "header to row", "headers as data"), local_only=True, adds_rows=True)


# ===================================================================== rows

ROWS = "Rows"


def _positional(name: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        return extension(node, name, {key: params.get(key) for key in ("count", "seed", "numbers")},
                         dict(node.schema()))

    return build


@handles("rows.keep_last")
def _keep_last(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    return frame.tail(int(config["count"])).reset_index(drop=True)


@handles("rows.skip_last")
def _skip_last(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    count = int(config["count"])
    return frame.iloc[: max(len(frame) - count, 0)].reset_index(drop=True)


@handles("rows.reverse")
def _reverse(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    return frame.iloc[::-1].reset_index(drop=True)


@handles("rows.shuffle")
def _shuffle(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    order = np.random.default_rng(int(config.get("seed") or 1)).permutation(len(frame))
    return frame.iloc[order].reset_index(drop=True)


@handles("rows.delete")
def _delete(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    try:
        numbers = {int(item) for item in config.get("numbers") or []}
    except ValueError:
        raise BadRequestError("Row numbers are whole numbers, counted from 1.") from None
    keep = [position for position in range(len(frame)) if position + 1 not in numbers]
    return frame.iloc[keep].reset_index(drop=True)


_COUNT = Param("count", "How many", ParamKind.INTEGER, default=10, minimum=0, maximum=100_000_000)
_FIVE = tuple({"n": n} for n in range(1, 6))
_declare("rows.keep_last", "Keep the last rows", ROWS, "Keep this many rows from the end, in their order.",
         _positional("rows.keep_last"), Example(rows=_FIVE, params={"count": 2}, column="n", output="n",
                                                expect=(4, 5)),
         params=(_COUNT,), synonyms=("tail", "last n", "keep bottom", "bottom rows"), local_only=True)
_declare("rows.skip_last", "Skip the last rows", ROWS, "Drop this many rows from the end (a totals line, a "
         "footer).", _positional("rows.skip_last"),
         Example(rows=_FIVE, params={"count": 2}, column="n", output="n", expect=(1, 2, 3)),
         params=(_COUNT,), synonyms=("drop last", "remove footer", "skip bottom", "drop trailing rows"),
         local_only=True)
_declare("rows.reverse", "Reverse the rows", ROWS, "Put the rows in the opposite order.", _positional("rows.reverse"),
         Example(rows=_FIVE[:3], column="n", output="n", expect=(3, 2, 1)),
         synonyms=("reverse order", "flip", "upside down", "invert rows"), local_only=True)
_declare("rows.shuffle", "Shuffle the rows", ROWS, "Put the rows in a random order that is the same every run "
         "for the same seed.", _positional("rows.shuffle"),
         Example(rows=_FIVE, params={"seed": 1}, column="n", output="n", expect=(5, 1, 2, 3, 4)),
         params=(Param("seed", "Seed", ParamKind.INTEGER, required=False, default=1, minimum=0),),
         synonyms=("shuffle", "randomise order", "random order", "permute"), local_only=True)
_declare("rows.delete", "Delete rows by number", ROWS, "Delete the rows at these positions, counted from 1 in "
         "the order the rows are in.", _positional("rows.delete"),
         Example(rows=_FIVE, params={"numbers": ["2", "4"]}, column="n", output="n", expect=(1, 3, 5)),
         params=(Param("numbers", "Row numbers", ParamKind.LIST, placeholder="1\n7"),),
         synonyms=("delete row", "remove row", "drop row number"), local_only=True)


def _insert_build(node: Node, params: dict[str, Any]) -> Node:
    values: dict[str, str] = {}
    for line in params["values"]:
        if "=" not in line:
            raise BadRequestError(f"Write each value as column=value, not {line!r}.")
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in node.schema():
            raise BadRequestError(f"{name!r} is not a column here. Columns: {', '.join(node.schema())}.")
        values[name] = value.strip()
    return extension(node, "rows.insert", {"values": values, "where": params.get("where") or "at the end"},
                     dict(node.schema()))


@handles("rows.insert")
def _insert(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    row: dict[str, Any] = {}
    for name, value in (config.get("values") or {}).items():
        series = frame[name]
        if pd.api.types.is_bool_dtype(series):
            row[name] = str(value).lower() in ("true", "yes", "1")
        elif pd.api.types.is_numeric_dtype(series):
            converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            row[name] = None if pd.isna(converted) else converted
        elif pd.api.types.is_datetime64_any_dtype(series):
            row[name] = pd.to_datetime(value, errors="coerce")
        else:
            row[name] = value
    added = pd.DataFrame([row], columns=frame.columns)
    parts = [added, frame] if config.get("where") == "at the start" else [frame, added]
    return pd.concat([part for part in parts if len(part.columns)], ignore_index=True)


_declare("rows.insert", "Add a row", ROWS, "Add one row with the values given, at the start or the end; columns "
         "not named are empty.", _insert_build,
         Example(rows=({"item": "tea", "qty": 2},), params={"values": ["item=total", "qty=2"]}, column="item",
                 output="item", expect=("tea", "total")),
         params=(Param("values", "Values", ParamKind.LIST, placeholder="item=total\nqty=0"),
                 Param("where", "Where", ParamKind.SELECT, required=False, default="at the end",
                       options=("at the end", "at the start"))),
         synonyms=("insert row", "add row", "append row", "new row"), local_only=True, adds_rows=True)


_COLUMN = Param("column", "Column", ParamKind.COLUMN)


def _custom_order(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    order = [str(item) for item in params["order"]]
    if not order:
        raise BadRequestError("List the values in the order wanted.")
    rank = Case(tuple((Call("eq", (Cast(Column(column), STRING), Literal(value, STRING))), Literal(index, INT64))
                      for index, value in enumerate(order, start=1)), Literal(len(order) + 1, INT64))
    return Sort(node, (SortKey(rank, "asc", False),))


_declare("rows.custom_order", "Sort in a chosen order", ROWS, "Put rows in the order of a list of values (Low, "
         "Medium, High; Mon to Sun); values not in the list come after.", _custom_order,
         Example(rows=({"size": "M"}, {"size": "XL"}, {"size": "S"}, {"size": "L"}),
                 params={"order": ["S", "M", "L"]}, column="size", output="size", expect=("S", "M", "L", "XL")),
         params=(_COLUMN, Param("order", "Values in order", ParamKind.LIST, placeholder="Low\nMedium\nHigh")),
         synonyms=("custom sort", "sort by list", "manual order", "ordinal sort"))

_CONVERTS = {"a number": "to_number", "a whole number": "to_integer", "a date": "to_date",
             "true or false": "to_boolean"}


def _errors(keep: bool):
    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        converted = Call(_CONVERTS[params.get("as") or "a number"], (Column(column),))
        failed = Call("and", (Call("is_not_null", (Column(column),)), Call("is_null", (converted,))))
        return Filter(node, failed if keep else Call("not", (failed,)))

    return build


_AS = Param("as", "Should be", ParamKind.SELECT, required=False, default="a number", options=tuple(_CONVERTS))
_declare("rows.keep_errors", "Keep rows that do not convert", ROWS, "Keep only the rows whose value cannot be read "
         "as a number, a date or true or false, to see what is wrong.", _errors(True),
         Example(rows=({"v": "12"}, {"v": "twelve"}, {"v": None}), column="v", output="v", expect=("twelve",)),
         params=(_COLUMN, _AS), synonyms=("keep errors", "show bad values", "invalid rows", "rows that fail"))
_declare("rows.remove_errors", "Drop rows that do not convert", ROWS, "Drop the rows whose value cannot be read "
         "as a number, a date or true or false; empty values stay.", _errors(False),
         Example(rows=({"v": "12"}, {"v": "twelve"}, {"v": None}), column="v", output="v", expect=("12", None)),
         params=(_COLUMN, _AS), synonyms=("remove errors", "drop bad values", "drop invalid rows"), null_answer=True)


# ================================================================== reshape

RESHAPE = "Reshape"


def _transpose_build(node: Node, params: dict[str, Any]) -> Node:
    header = params.get("header")
    if header:
        require_column(node, header)
    return extension(node, "reshape.transpose", {"header": header or None}, None)


@handles("reshape.transpose")
def _transpose(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        # Nothing turned on its side is still nothing.
        return pd.DataFrame({"column": pd.Series(dtype=object)})
    header = config.get("header")
    body = frame.set_index(header) if header else frame
    flipped = body.T.reset_index()
    flipped.columns = ["column", *[str(name) if header else f"row_{index + 1}"
                                   for index, name in enumerate(body.index)]]
    if len(set(flipped.columns)) != len(flipped.columns):
        seen: dict[str, int] = {}
        renamed = []
        for name in flipped.columns:
            seen[name] = seen.get(name, 0) + 1
            renamed.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
        flipped.columns = renamed
    return flipped.infer_objects()


_declare("reshape.transpose", "Swap rows and columns", RESHAPE, "Turn each column into a row and each row into a "
         "column, naming the new columns from a column of your choice (or row_1, row_2).", _transpose_build,
         Example(rows=({"metric": "sales", "jan": 10, "feb": 12}, {"metric": "costs", "jan": 4, "feb": 5}),
                 params={"header": "metric"}, column="metric", output="sales", expect=(10, 12)),
         params=(Param("header", "Name the new columns from", ParamKind.COLUMN, required=False),),
         synonyms=("transpose", "flip rows and columns", "rotate", "swap axes"), local_only=True,
         dynamic_columns=True)


def _nest_build(node: Node, params: dict[str, Any]) -> Node:
    columns = columns_of(node, params["columns"], "Columns")
    into = (params.get("into") or "details").strip()
    keep = [name for name in node.schema() if not (params.get("drop", True) and name in columns)]
    if into in keep:
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    schema = {name: node.schema()[name] for name in keep}
    schema[into] = JSON_TYPE
    return extension(node, "reshape.nest", {"columns": columns, "into": into, "keep": keep}, schema)


@handles("reshape.nest")
def _nest(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    columns = list(config["columns"])
    out = frame[list(config["keep"])].copy()

    def plain(value: Any) -> Any:
        if pd.isna(value):
            return None
        if isinstance(value, np.generic):
            return value.item()
        return value.isoformat() if isinstance(value, pd.Timestamp) else value

    out[config["into"]] = [json.dumps({name: plain(value) for name, value in zip(columns, row)}, default=str)
                           for row in frame[columns].itertuples(index=False, name=None)]
    return out


_declare("reshape.nest", "Combine columns into one", RESHAPE, "Put several columns into one JSON column, for "
         "an API that wants an object or a document store.", _nest_build,
         Example(rows=({"id": 1, "city": "Leeds", "zip": "LS1"},), params={"columns": ["city", "zip"],
                                                                         "into": "address"},
                 column="id", output="address", expect=('{"city": "Leeds", "zip": "LS1"}',)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS), Param("into", "New column", ParamKind.TEXT,
                                                                        default="details"),
                 Param("drop", "Drop the originals", ParamKind.BOOLEAN, required=False, default=True)),
         synonyms=("nest columns", "to struct", "combine into json", "pack columns", "object column"),
         local_only=True, row_wise=True)


def _crosstab_build(node: Node, params: dict[str, Any]) -> Node:
    columns_of(node, [params["rows"], params["columns"], *([params["values"]] if params.get("values") else [])],
               "Cross-tab")
    return extension(node, "reshape.crosstab", {key: params.get(key) for key in ("rows", "columns", "values",
                                                                                 "function")}, None)


@handles("reshape.crosstab")
def _crosstab(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows, columns = config["rows"], config["columns"]
    function = config.get("function") or "count"
    if function != "count" and not config.get("values"):
        raise BadRequestError(f"Say which column to {function}.")
    if frame.empty:
        return pd.DataFrame({rows: pd.Series(dtype=object)})
    if function == "count":
        table = pd.crosstab(frame[rows].fillna("(empty)"), frame[columns].fillna("(empty)"))
    else:
        values = pd.to_numeric(frame[config["values"]], errors="coerce")
        table = pd.crosstab(frame[rows].fillna("(empty)"), frame[columns].fillna("(empty)"), values=values,
                            aggfunc={"sum": "sum", "average": "mean", "lowest": "min", "highest": "max"}[function])
    table.columns = [str(name) for name in table.columns]
    return table.reset_index().rename(columns={rows: rows})


_declare("reshape.crosstab", "Cross-tab two columns", RESHAPE, "Count (or total) rows by two columns at once: one "
         "row per value of the first, one column per value of the second.", _crosstab_build,
         Example(rows=({"shop": "a", "day": "mon"}, {"shop": "a", "day": "tue"}, {"shop": "b", "day": "mon"}),
                 params={"rows": "shop", "columns": "day"}, column="shop", output="mon", expect=(1, 1)),
         params=(Param("rows", "One row per", ParamKind.COLUMN), Param("columns", "One column per", ParamKind.COLUMN),
                 Param("function", "Show", ParamKind.SELECT, required=False, default="count",
                       options=("count", "sum", "average", "lowest", "highest")),
                 Param("values", "Of column", ParamKind.COLUMN, required=False)),
         synonyms=("cross tab", "crosstab", "contingency table", "two way table", "matrix count"),
         local_only=True, dynamic_columns=True)
