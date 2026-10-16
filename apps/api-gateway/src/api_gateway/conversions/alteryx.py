"""An Alteryx workflow (.yxmd) to recipes (E2, X3).

Read as Alteryx publishes the format: ``<Nodes>`` of tools, each with its
plugin and ``<Configuration>``, and ``<Connections>`` from one tool's output
to another's input. Each output (Output Data) becomes a recipe of the tools
before it (``flows.py``); an Input Data is a dataset the project has,
matched by its file's name, and a Text Input is data the file carries.

Tools converted: Input Data, Text Input, Select, Filter (both outputs),
Formula, Sort, Summarize, Join (J, L and R outputs), Union (by name),
Unique (its unique rows), Sample (first or last rows), Record ID, Output
Data, and Browse, Comment and Container, which change nothing.

Expressions follow Alteryx's published null rules: text plus an empty value
is the text, a number plus an empty value is empty, an empty value equals
only another empty value, and a comparison with an empty side is false,
never empty. Join matches two empty keys, as Alteryx's does. A function
whose answer Alteryx does not document exactly (Round, ToNumber, ToString,
Mod) is refused, not guessed.
"""

from __future__ import annotations

import csv
import io
import posixpath
import re

from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import UNKNOWN, timestamp

from service_transformations.formula.printer import if_chain
from service_transformations.ir.expressions import Column, Expr, Literal

from api_gateway.conversions import expressions as ex
from api_gateway.conversions.expressions import FALSE, NULL, TRUE, Language, Parser, call, iif
from api_gateway.conversions.flows import (
    Component,
    Flow,
    Stream,
    derive,
    distinct,
    join,
    keep_rows,
    limit,
    rename,
    select,
    sort,
    sql,
)
from api_gateway.conversions.model import Conversion, NotConverted, Seed
from api_gateway.conversions.xmlfiles import attribute, child, children, items, read_xml

_TYPES: dict[str, PWType] = {
    "Bool": BOOLEAN, "Byte": INT64, "Int16": INT64, "Int32": INT64, "Int64": INT64, "Float": FLOAT64,
    "Double": FLOAT64, "FixedDecimal": FLOAT64, "String": STRING, "WString": STRING, "V_String": STRING,
    "V_WString": STRING, "Date": DATE, "DateTime": timestamp(), "Time": STRING,
}
_TEXT_TYPES = {"String", "WString", "V_String", "V_WString"}
_WHOLE_TYPES = {"Byte", "Int16", "Int32", "Int64"}


# ============================================================ expressions


def _plus(parser: Parser, a: Expr, b: Expr) -> Expr:
    if parser.is_text(a) or parser.is_text(b):
        return ex.concat_ignoring_empty(a, b)
    if parser.is_number(a) and parser.is_number(b):
        return call("add", a, b)
    raise parser.refuse("+ joins text or adds numbers; this cannot tell which from the columns it reads.")


def _arithmetic(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        if not (parser.is_number(a) and parser.is_number(b)):
            raise parser.refuse(f"{ {'sub': '-', 'mul': '*', 'div': '/'}[name]} works on numbers here.")
        return call(name, a, b)

    return build


def _compare(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        if name == "eq":
            return ex.equal_with_empty(a, b)
        if name == "ne":
            return call("not", ex.equal_with_empty(a, b))
        compared = ex.two_valued(call(name, a, b))
        if name in ("le", "ge") and not (ex.never_empty(a) or ex.never_empty(b)):
            # True with an empty side only when both are empty (Alteryx's rule).
            return call("or", call("and", call("is_null", a), call("is_null", b)), compared)
        return compared

    return build


def _if_special(parser: Parser, token) -> Expr | None:
    if token.kind != "name" or parser.word(token) != "IF":
        return None
    parser.advance()
    branches = []
    condition = parser.expression(0)
    parser.expect("name", "THEN")
    branches.append((condition, parser.expression(0)))
    default = None
    while True:
        if parser.at_word("ELSEIF"):
            parser.advance()
            condition = parser.expression(0)
            parser.expect("name", "THEN")
            branches.append((condition, parser.expression(0)))
            continue
        if parser.at_word("ELSE"):
            parser.advance()
            default = parser.expression(0)
        parser.expect("name", "ENDIF")
        return if_chain(branches, default)


def _in_postfix(parser: Parser, left: Expr, token, minimum: int) -> Expr | None:
    if token.kind == "name" and parser.word(token) in ("IN", "NOT") and minimum <= 40:
        negate = parser.word(token) == "NOT"
        if negate:
            following = parser.tokens[parser.index + 1]
            if following.kind != "name" or following.text.upper() != "IN":
                return None
            parser.advance()
        parser.advance()
        values = parser.arguments()
        if not values or not all(isinstance(v, Literal) and v.value is not None for v in values):
            raise parser.refuse("IN takes a list of values written in.")
        found = ex.two_valued(call("in_list", left, *values))
        return call("not", found) if negate else found
    return None


def _need(count: int | tuple[int, ...], name: str):
    def check(parser: Parser, args: list[Expr]) -> None:
        allowed = (count,) if isinstance(count, int) else count
        if len(args) not in allowed:
            raise parser.refuse(f"{name}() takes {' or '.join(str(n) for n in allowed)} arguments here.")

    return check


def _fn(name: str, count, build):
    check = _need(count, name)

    def function(parser: Parser, args: list[Expr]) -> Expr:
        check(parser, args)
        return build(parser, args)

    return function


def _case_insensitive(ir_name: str, name: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        needle = ex.text_literal(parser, args[1], f"What {name}() looks for")
        if len(args) == 3 and ex.whole_literal(parser, args[2], f"{name}()'s third argument") == 0:
            return call(ir_name, args[0], Literal(needle, STRING))
        return call(ir_name, call("lower", args[0]), Literal(needle.lower(), STRING))

    return build


def _substring(parser: Parser, args: list[Expr]) -> Expr:
    start = ex.whole_literal(parser, args[1], "Substring()'s start")
    if start < 0:
        raise parser.refuse("Substring() starts at a position from 0.")
    if len(args) == 3:
        length = ex.whole_literal(parser, args[2], "Substring()'s length")
        return call("substring", args[0], Literal(start + 1, INT64), Literal(length, INT64))
    return call("substring", args[0], Literal(start + 1, INT64))


def _is_empty(parser: Parser, args: list[Expr]) -> Expr:
    if parser.is_text(args[0]):
        return call("or", call("is_null", args[0]), ex.two_valued(call("eq", args[0], Literal("", STRING))))
    return call("is_null", args[0])


def _refused(name: str, reason: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        raise parser.refuse(f"{name}() {reason}")

    return build


_UNDOCUMENTED = "is not converted: Alteryx's help does not say exactly what it gives for every value (a half, an " \
                "empty value or text that is not a number), and this does not guess."

ALTERYX = Language(
    name="Alteryx",
    infix={
        "OR": (10, lambda p, a, b: call("or", a, b)), "||": (10, lambda p, a, b: call("or", a, b)),
        "AND": (20, lambda p, a, b: call("and", a, b)), "&&": (20, lambda p, a, b: call("and", a, b)),
        "=": (40, _compare("eq")), "==": (40, _compare("eq")), "!=": (40, _compare("ne")),
        "<>": (40, _compare("ne")), "<": (40, _compare("lt")), "<=": (40, _compare("le")),
        ">": (40, _compare("gt")), ">=": (40, _compare("ge")),
        "+": (50, _plus), "-": (50, _arithmetic("sub")), "*": (60, _arithmetic("mul")),
        "/": (60, _arithmetic("div")),
    },
    prefix={"NOT": (30, lambda p, a: call("not", a)), "!": (30, lambda p, a: call("not", a)),
            "-": (70, lambda p, a: call("neg", a))},
    functions={
        "IIF": _fn("IIF", 3, lambda p, a: iif(a[0], a[1], a[2])),
        "ISNULL": _fn("IsNull", 1, lambda p, a: call("is_null", a[0])),
        "ISEMPTY": _fn("IsEmpty", 1, _is_empty),
        "NULL": _fn("Null", 0, lambda p, a: NULL),
        "TRIM": _fn("Trim", 1, lambda p, a: call("trim", a[0])),
        "TRIMLEFT": _fn("TrimLeft", 1, lambda p, a: call("ltrim", a[0])),
        "TRIMRIGHT": _fn("TrimRight", 1, lambda p, a: call("rtrim", a[0])),
        "UPPERCASE": _fn("Uppercase", 1, lambda p, a: call("upper", a[0])),
        "LOWERCASE": _fn("Lowercase", 1, lambda p, a: call("lower", a[0])),
        "LENGTH": _fn("Length", 1, lambda p, a: call("length", a[0])),
        "LEFT": _fn("Left", 2, lambda p, a: call("left", a[0], Literal(ex.whole_literal(p, a[1], "Left()'s count"),
                                                                       INT64))),
        "RIGHT": _fn("Right", 2, lambda p, a: call("right", a[0], Literal(ex.whole_literal(p, a[1],
                                                                                           "Right()'s count"), INT64))),
        "SUBSTRING": _fn("Substring", (2, 3), _substring),
        "CONTAINS": _fn("Contains", (2, 3), _case_insensitive("contains", "Contains")),
        "STARTSWITH": _fn("StartsWith", (2, 3), _case_insensitive("starts_with", "StartsWith")),
        "ENDSWITH": _fn("EndsWith", (2, 3), _case_insensitive("ends_with", "EndsWith")),
        "REPLACE": _fn("Replace", 3, lambda p, a: call(
            "replace", a[0], Literal(ex.text_literal(p, a[1], "What Replace() finds"), STRING),
            Literal(ex.text_literal(p, a[2], "What Replace() puts"), STRING))),
        "ABS": _fn("ABS", 1, lambda p, a: call("abs", a[0])),
        "CEIL": _fn("CEIL", 1, lambda p, a: call("ceil", a[0])),
        "FLOOR": _fn("FLOOR", 1, lambda p, a: call("floor", a[0])),
        "POW": _fn("POW", 2, lambda p, a: call("power", a[0], a[1])),
        "SQRT": _fn("SQRT", 1, lambda p, a: call("sqrt", a[0])),
        "DATETIMEYEAR": _fn("DateTimeYear", 1, lambda p, a: call("year", a[0])),
        "DATETIMEMONTH": _fn("DateTimeMonth", 1, lambda p, a: call("month", a[0])),
        "DATETIMEDAY": _fn("DateTimeDay", 1, lambda p, a: call("day", a[0])),
        **{name.upper(): _refused(name, _UNDOCUMENTED) for name in ("Round", "ToNumber", "ToString", "Mod",
                                                                     "Min", "Max", "TitleCase")},
    },
    constants={"TRUE": TRUE, "FALSE": FALSE},
    special=_if_special,
    postfix=_in_postfix,
)
_OPERATORS = ("==", "!=", "<>", "<=", ">=", "&&", "||", "=", "<", ">", "+", "-", "*", "/", "!")


def expression(text: str, columns: dict[str, PWType], what: str) -> Expr:
    return ex.parse(text, ALTERYX, columns, what=what, quotes="\"'", escape="double", brackets=True,
                    operators=_OPERATORS)


# ================================================================= the file


def convert_alteryx(files: dict[str, bytes], lookup) -> Conversion:
    (name, data), = files.items()
    root = read_xml(data, name)
    if root.tag != "AlteryxDocument":
        raise NotConverted(f"{name} is not an Alteryx workflow (its root is {root.tag}, not AlteryxDocument).")
    title = posixpath.splitext(posixpath.basename(name))[0]
    conversion = Conversion(format="alteryx", title=f"the Alteryx workflow {title}")
    flow = Flow(conversion, title, f"alteryx:{title}")
    nodes = {}
    for node in root.iter("Node"):
        tool_id = attribute(node, "ToolID")
        gui = child(node, "GuiSettings")
        plugin = (attribute(gui, "Plugin") or "") if gui is not None else ""
        if tool_id:
            nodes[tool_id] = (plugin, node)
    inputs: dict[str, dict[str, tuple[str, str]]] = {tool_id: {} for tool_id in nodes}
    connections = child(root, "Connections")
    for connection in (children(connections, "Connection") if connections is not None else []):
        origin, destination = child(connection, "Origin"), child(connection, "Destination")
        if origin is None or destination is None:
            continue
        port = attribute(destination, "Connection") or "Input"
        named = attribute(connection, "name")
        if named:
            port = f"{port} {named}"
        target = attribute(destination, "ToolID")
        if target in inputs:
            inputs[target][port] = (attribute(origin, "ToolID") or "", attribute(origin, "Connection") or "Output")
    for tool_id, (plugin, node) in nodes.items():
        kind = plugin.rsplit(".", 1)[-1] if plugin else "Macro"
        label = f"{_TOOL_WORDS.get(kind, kind)} (tool {tool_id})"
        section = conversion.section(f"{name}: {label}")
        writes = _output_name(node) if kind == "DbFileOutput" else None
        build = _build(kind, node, label, lookup, conversion, title, section)
        flow.add(Component(tool_id, label, inputs.get(tool_id, {}), build, section, writes=writes))
    flow.outputs()
    flow.unused()
    for component in flow.components.values():
        if component.writes is None and not component.section.entries:
            # Converted, and read by an output: its steps are in the outputs' recipes.
            component.section.converted(component.label, "Its steps are in the recipes of the outputs after it")
    _run_all(conversion)
    conversion.notes.append("The workflow is read, never run: no tool of it ran here.")
    return conversion


_TOOL_WORDS = {
    "DbFileInput": "Input Data", "TextInput": "Text Input", "AlteryxSelect": "Select", "Filter": "Filter",
    "Formula": "Formula", "Sort": "Sort", "Summarize": "Summarize", "Join": "Join", "Union": "Union",
    "Unique": "Unique", "Sample": "Sample", "RecordID": "Record ID", "DbFileOutput": "Output Data",
    "BrowseV2": "Browse", "Browse": "Browse", "TextBox": "Comment", "ToolContainer": "Container",
}


def _configuration(node):
    return child(child(node, "Properties"), "Configuration")


def _output_name(node) -> str:
    file = child(_configuration(node), "File")
    path = (file.text or "").strip() if file is not None else ""
    return posixpath.splitext(posixpath.basename(path.replace("\\", "/")))[0] or "output"


def _declared(node) -> dict[str, tuple[PWType, str]]:
    """The fields a tool's own metadata says it gives: name -> (type, Alteryx's type)."""
    found = {}
    for meta in items(child(node, "Properties")):
        if meta.tag == "MetaInfo":
            for field in meta.iter("Field"):
                kind = attribute(field, "type") or ""
                found[attribute(field, "name") or ""] = (_TYPES.get(kind, UNKNOWN), kind)
            break
    return found


def _build(kind: str, node, label: str, lookup, conversion: Conversion, title: str, section):
    config = _configuration(node)
    if kind == "DbFileInput":
        return _input(node, config, label, lookup, conversion)
    if kind == "TextInput":
        return _text_input(node, config, label, conversion, title)
    builders = {"AlteryxSelect": _select, "Filter": _filter, "Formula": _formula, "Sort": _sort,
                "Summarize": _summarize, "Join": _join, "Union": _union, "Unique": _unique, "Sample": _sample,
                "RecordID": _record_id, "DbFileOutput": _pass_through}
    if kind in builders:
        return builders[kind](config, label)
    if kind in ("BrowseV2", "Browse", "TextBox", "ToolContainer"):
        section.nothing_to_do(label, "It shows the rows or holds a note; it changes no data.")
        return None
    return _not(f"{_TOOL_WORDS.get(kind, kind)} is not a tool this converts.")


def _not(reason: str):
    def build(flow: Flow, inputs: dict[str, Stream]) -> dict[str, Stream]:
        raise NotConverted(reason)

    return build


def _one(inputs: dict[str, Stream]) -> Stream:
    if not inputs:
        raise NotConverted("Nothing is connected to its input.")
    return next(iter(inputs.values()))


def _pass_through(config, label):
    return lambda flow, inputs: {"Output": _one(inputs)}


def _input(node, config, label, lookup, conversion: Conversion):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        file = child(config, "File")
        path = (file.text or "").strip().replace("\\", "/") if file is not None else ""
        if not path:
            raise NotConverted("It reads no file.")
        name = posixpath.splitext(posixpath.basename(path))[0]
        declared = _declared(node)
        need = conversion.need(f"file:{name.lower()}", name, f"the file {posixpath.basename(path)}",
                               columns=list(declared), types={k: v[0] for k, v in declared.items()})
        columns = lookup(need)
        if columns is None:
            raise NotConverted(f"It reads {posixpath.basename(path)}. Choose the dataset that holds it (none here is "
                               f"called “{name}”), then read the workflow again.")
        missing = [field for field in declared if field not in columns]
        if missing:
            raise NotConverted(f"The dataset chosen for {posixpath.basename(path)} has no column {missing[0]}.")
        stream = Stream(need.key, [], dict(columns))
        if declared and list(declared) != list(columns):
            stream = select(stream, list(declared), "Keep the fields the file gives, in its order")
        flow.converted(flow.labelled(label), f"Reads the dataset “{name}”")
        return {"Output": stream}

    return build


def _text_input(node, config, label, conversion: Conversion, title: str):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        fields = [attribute(f, "name") or "" for f in items(child(config, "Fields"))]
        rows = [[(c.text or "") for c in row] for row in items(child(config, "Data"))]
        if not fields:
            raise NotConverted("It holds no fields.")
        if any(cell == "" for row in rows for cell in row):
            raise NotConverted("A cell of it is empty: in Alteryx that is empty text, and a dataset here cannot tell "
                               "empty text from no value.")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(fields)
        writer.writerows(rows)
        seed_name = f"{title} · {label}"[:160]
        key = f"seed:{label}"
        conversion.seeds.append(Seed(key=key, name=seed_name, what=f"the data in {label}",
                                     file_name=f"{re.sub(r'[^A-Za-z0-9]+', '_', label).strip('_')}.csv",
                                     data=buffer.getvalue().encode()))
        from api_gateway.conversions.dbt import _seed_columns

        columns = _seed_columns(buffer.getvalue().encode())
        stream = Stream(key, [], columns)
        declared = _declared(node)
        texts = [f for f, (_, kind) in declared.items() if kind in _TEXT_TYPES and f in columns
                 and columns[f].kind is not STRING.kind]
        if texts:
            stream = stream.then({"step_type": "cast_column_types", "config": {"mappings": {f: "string" for f in
                                                                                         texts}}},
                                 f"Keep {', '.join(texts)} as text, as the tool types them")
        flow.converted(flow.labelled(label), f"The dataset “{seed_name}”, made from its "
                                                              f"{len(rows)} rows")
        return {"Output": stream}

    return build


def _select(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        fields = children(child(config, "SelectFields"), "SelectField") if child(config, "SelectFields") is not None \
            else []
        return {"Output": _apply_select(stream, fields, label, reorder=_order_changed(config))}

    return build


def _apply_select(stream: Stream, fields, label: str, *, reorder: bool = True) -> Stream:
    listed = {}
    order: list[str] = []
    truncating: list[tuple[str, int]] = []
    unknown_kept, unknown_at = True, None
    for field in fields:
        name = attribute(field, "field") or ""
        if name == "*Unknown":
            unknown_kept = (attribute(field, "selected") or "True") == "True"
            unknown_at = len(order)
            continue
        if name not in stream.columns:
            continue  # a field the tool knew that the rows no longer have: Alteryx leaves it out too
        selected = (attribute(field, "selected") or "True") == "True"
        new_type = attribute(field, "type")
        if selected and new_type:
            # A type kept in its family changes no value; a change of family is
            # a conversion whose every value Alteryx's help does not give.
            if _family(_TYPES.get(new_type, UNKNOWN)) != _family(stream.columns[name]):
                raise NotConverted(f"It changes the type of {name} to {new_type}, which this does not convert.")
            size = attribute(field, "size")
            if new_type in _TEXT_TYPES and size and size.isdigit():
                truncating.append((name, int(size)))
        listed[name] = (selected, attribute(field, "rename") or name)
        order.append(name)
    rest = [name for name in stream.columns if name not in listed]
    if unknown_at is None:
        unknown_at = len(order)
    names = order[:unknown_at] + (rest if unknown_kept else []) + order[unknown_at:]
    if not reorder:
        # Order not changed: the fields keep the order they came in.
        names = [name for name in stream.columns if name in listed or unknown_kept]
    kept = [name for name in names if listed.get(name, (True, name))[0]]
    stream = select(stream, kept, "Keep and order its fields (Select)")
    for name, size in truncating:
        if name in kept:
            # Alteryx cuts a text to its field's new size.
            stream = derive(stream, name, call("left", Column(name), Literal(size, INT64)),
                            f"Cut {name} to {size} characters (Select)")
    return rename(stream, {name: listed[name][1] for name in kept if name in listed}, "Rename its fields (Select)")


def _order_changed(config) -> bool:
    flag = child(config, "OrderChanged") if config is not None else None
    return (attribute(flag, "value") or "False") == "True" if flag is not None else False


def _family(kind: PWType) -> str:
    value = kind.kind.value
    if value.startswith(("int", "uint")):
        return "whole"
    if value.startswith(("float", "decimal")):
        return "decimal"
    return value


def _filter(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        node = child(config, "Expression")
        text = (node.text or "").strip() if node is not None else ""
        if not text:
            raise NotConverted("Its condition is not written in the file (a Simple filter with no expression).")
        condition = expression(text, stream.columns, f"The condition {text!r}")
        flow.converted(flow.labelled(label), f"Keep the rows where {text} (T); the rest (F)")
        return {"True": keep_rows(stream, condition, f"Keep the rows where {text}"),
                "False": keep_rows(stream, condition, f"Keep the rows where {text} is not true", keep=False)}

    return build


def _formula(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        fields = children(child(config, "FormulaFields"), "FormulaField") if child(config, "FormulaFields") is not \
            None else []
        if not fields:
            raise NotConverted("It has no formulas.")
        lines = []
        for field in fields:
            name = attribute(field, "field") or ""
            text = attribute(field, "expression") or ""
            kind = attribute(field, "type")
            what = f"The formula for {name}"
            value = expression(text, stream.columns, what)
            parser = Parser([], ALTERYX, stream.columns, what)
            if name in stream.columns and not kind:
                kind = None
            if kind in _TEXT_TYPES:
                if not parser.is_text(value):
                    raise NotConverted(f"{what} makes a {parser.kind(value).value} into {kind}, a conversion "
                                       "whose every value Alteryx's help does not give.")
                size = attribute(field, "size")
                if size and size.isdigit() and int(size) < 2_147_483_647:
                    # Alteryx cuts a text to its field's size.
                    value = call("left", value, Literal(int(size), INT64))
            elif kind in _WHOLE_TYPES and not parser.is_whole(value):
                raise NotConverted(f"{what} makes a {parser.kind(value).value} into a whole number ({kind}), which "
                                   "Alteryx rounds in a way its help does not give.")
            elif kind in ("Double", "Float") and not parser.is_number(value):
                raise NotConverted(f"{what} makes a {parser.kind(value).value} into a number ({kind}).")
            elif kind in ("FixedDecimal",):
                raise NotConverted(f"{what} is a FixedDecimal, which Alteryx rounds to its places in a way this "
                                   "does not convert.")
            elif kind == "Bool" and parser.kind(value).value not in ("boolean", "unknown"):
                raise NotConverted(f"{what} makes a {parser.kind(value).value} into true or false.")
            stream = derive(stream, name, value, f"Work out {name} = {text}")
            lines.append(f"{name} = {text}")
        flow.converted(flow.labelled(label), [f"Work out {line}" for line in lines])
        return {"Output": stream}

    return build


def _sort(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        fields = list(items(child(config, "SortInfo")))
        if not fields:
            raise NotConverted("It sorts by nothing.")
        # Alteryx puts empty values last in ascending order and first in descending.
        keys = [(attribute(f, "field") or "", (attribute(f, "order") or "Ascending") == "Ascending",
                 (attribute(f, "order") or "Ascending") != "Ascending") for f in fields]
        flow.converted(flow.labelled(label), "Sort by " + ", ".join(
            f"{k} {'ascending' if a else 'descending'}" for k, a, _ in keys))
        return {"Output": sort(stream, keys, "Sort (" + ", ".join(k for k, _, _ in keys) + ")")}

    return build


_SUMMARY = {"Sum": "SUM({})", "Count": "COUNT(*)", "CountNonNull": "COUNT({})", "CountDistinct": "COUNT(DISTINCT {})",
            "Min": "MIN({})", "Max": "MAX({})", "Avg": "AVG({})", "Median": "MEDIAN({})",
            "CountNull": "SUM(CASE WHEN {} IS NULL THEN 1 ELSE 0 END)"}


def _summarize(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        fields = children(child(config, "SummarizeFields"), "SummarizeField") if child(config, "SummarizeFields") \
            is not None else []
        groups, items = [], []
        for field in fields:
            name, action = attribute(field, "field") or "", attribute(field, "action") or ""
            out = attribute(field, "rename") or name
            if name not in stream.columns and action != "Count":
                raise NotConverted(f"It summarises {name}, which the rows coming in do not have.")
            if action == "GroupBy":
                groups.append(name)
                items.append(f"{_q(name)} AS {_q(out)}" if out != name else _q(name))
            elif action in _SUMMARY:
                items.append(f"{_SUMMARY[action].format(_q(name))} AS {_q(out)}")
            else:
                raise NotConverted(f"Its {action} of {name} is not a summary this converts (Sum, Count, Count Non "
                                   "Null, Count Distinct, Count Null, Min, Max, Avg and Median are).")
        if not items:
            raise NotConverted("It summarises nothing.")
        text = f"SELECT {', '.join(items)} FROM input"
        if groups:
            # Alteryx gives the groups in the order of their values.
            grouped = ", ".join(_q(g) for g in groups)
            text += f" GROUP BY {grouped} ORDER BY " + ", ".join(f"{_q(g)} ASC NULLS LAST" for g in groups)
        flow.converted(flow.labelled(label), f"Summarise: {', '.join(items)}")
        return {"Output": sql(stream, text, "Summarise (Summarize)")}

    return build


def _q(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'


def _join(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        if "Left" not in inputs or "Right" not in inputs:
            raise NotConverted("It needs both its Left and its Right inputs connected.")
        if (attribute(config, "joinByRecordPos") or "False") == "True":
            raise NotConverted("It joins by record position, which this does not convert.")
        left, right = inputs["Left"], inputs["Right"]
        on, right_on = [], []
        for info in children(config, "JoinInfo"):
            names = [attribute(f, "field") or "" for f in children(info, "Field")]
            (on if attribute(info, "connection") == "Left" else right_on).extend(names)
        if not on or len(on) != len(right_on):
            raise NotConverted("Its Left and Right fields do not pair up.")
        right_key, right_columns = flow.dataset(right, f"{label} right")
        suffix = "__alteryx_right"
        joined = join(left, right_key, right_columns, how="inner", on=on, right_on=right_on,
                      bring=list(right_columns), suffix=suffix, line=f"Join with the right input on "
                                                                      f"{', '.join(on)} ({label}), empty keys "
                                                                      "matching each other")
        joined = rename(joined, {f"{name}{suffix}": f"Right_{name}" for name in right_columns if name in left.columns},
                        "Name the right input's repeated fields Right_ (Join)")
        select_config = child(config, "SelectConfiguration")
        fields = children(child(child(select_config, "Configuration"), "SelectFields"), "SelectField") if \
            select_config is not None and child(child(select_config, "Configuration"), "SelectFields") is not None \
            else []
        inner = child(select_config, "Configuration") if select_config is not None else None
        joined = _apply_select(joined, fields, label, reorder=_order_changed(inner)) if fields else joined
        left_only = left.then({"step_type": "tool", "config": {
            "tool": "join.sql", "right_dataset_id": {"$dataset": right_key}, "how": "anti", "on": on,
            "right_on": right_on, "bring": [], "empty_keys": "match each other"}},
            f"Keep the rows with no match in the right input ({label}, L)")
        def right_only() -> Stream:
            # Made only when something reads the R output: it needs the left input as a dataset.
            left_key, _ = flow.dataset(left, f"{label} left")
            return right.then({"step_type": "tool", "config": {
                "tool": "join.sql", "right_dataset_id": {"$dataset": left_key}, "how": "anti", "on": right_on,
                "right_on": on, "bring": [], "empty_keys": "match each other"}},
                f"Keep the rows with no match in the left input ({label}, R)")
        flow.converted(flow.labelled(label), [f"Join on {', '.join(on)} = {', '.join(right_on)}, two "
                                                         "empty keys matching (J); each side's unmatched rows (L, R)"])
        return {"Join": joined, "Left": left_only, "Right": right_only}

    return build


def _union(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        mode = (child(config, "Mode").text if child(config, "Mode") is not None else "ByName") or "ByName"
        ordered = [inputs[port] for port in sorted(inputs, key=lambda p: int(re.sub(r"\D", "", p) or 0))]
        if len(ordered) < 2:
            raise NotConverted("It has fewer than two inputs.")
        output_mode = (child(config, "ByName_OutputMode").text if child(config, "ByName_OutputMode") is not None
                       else "All") or "All"
        if mode != "ByName":
            raise NotConverted(f"It stacks by {mode}, which this does not convert; by name it does.")
        strategy = {"All": "union", "Common": "intersect"}.get(output_mode)
        if strategy is None:
            raise NotConverted(f"It keeps {output_mode} fields, which this does not convert.")
        stream = ordered[0]
        for index, other in enumerate(ordered[1:], start=2):
            key, columns = flow.dataset(other, f"{label} input {index}")
            step = {"step_type": "union_datasets", "config": {"other_dataset_id": {"$dataset": key},
                                                              "deduplicate": False, "column_strategy": strategy}}
            merged = dict(stream.columns)
            if strategy == "union":
                merged.update({name: kind for name, kind in columns.items() if name not in merged})
            else:
                merged = {name: kind for name, kind in merged.items() if name in columns}
            stream = stream.then(step, f"Add the rows of input {index}, by field name ({label})", columns=merged)
        flow.converted(flow.labelled(label), f"Stack {len(ordered)} inputs by field name")
        return {"Output": stream}

    return build


def _unique(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        fields = [attribute(f, "field") or "" for f in items(child(config, "UniqueFields"))]
        if not fields:
            raise NotConverted("It names no fields.")
        flow.converted(flow.labelled(label), f"Keep the first row of each {', '.join(fields)} (U); its D "
                                                        "output is not converted")
        return {"Unique": distinct(stream, fields, f"Keep the first row of each {', '.join(fields)}")}

    return build


def _sample(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        mode = (child(config, "Mode").text if child(config, "Mode") is not None else "") or ""
        count = (child(config, "N").text if child(config, "N") is not None else "") or ""
        if child(config, "GroupFields") is not None and len(child(config, "GroupFields")):
            raise NotConverted("It samples within groups, which this does not convert.")
        if not count.isdigit():
            raise NotConverted("Its number of rows is not a whole number.")
        if mode == "First":
            flow.converted(flow.labelled(label), f"Keep the first {count} rows")
            return {"Output": limit(stream, int(count), f"Keep the first {count} rows")}
        if mode == "Last":
            flow.converted(flow.labelled(label), f"Keep the last {count} rows")
            return {"Output": stream.then({"step_type": "tool", "config": {"tool": "rows.keep_last",
                                                                           "count": int(count)}},
                                          f"Keep the last {count} rows")}
        raise NotConverted(f"It samples by {mode or 'a mode it does not name'}, which this does not convert (First "
                           "and Last it does).")

    return build


def _record_id(config, label):
    def build(flow: Flow, inputs) -> dict[str, Stream]:
        stream = _one(inputs)
        name = (child(config, "FieldName").text if child(config, "FieldName") is not None else "RecordID") or \
            "RecordID"
        start = (child(config, "StartValue").text if child(config, "StartValue") is not None else "1") or "1"
        kind = (child(config, "FieldType").text if child(config, "FieldType") is not None else "Int32") or "Int32"
        position = (child(config, "Position").text if child(config, "Position") is not None else "0") or "0"
        if kind not in _WHOLE_TYPES or not start.lstrip("-").isdigit():
            raise NotConverted(f"It numbers rows as {kind} from {start}; this converts a whole number from a whole "
                               "number.")
        before = list(stream.columns)
        numbered = stream.then({"step_type": "tool", "config": {"tool": "window.row_number", "into": name}},
                               f"Number the rows from 1 ({name})")
        if int(start) != 1:
            offset = int(start) - 1
            numbered = derive(numbered, name, call("add", Column(name), ex.literal(offset)),
                              f"Start {name} at {start}")
        if position == "0":
            numbered = select(numbered, [name, *before], f"Put {name} first")
        flow.converted(flow.labelled(label), f"Number the rows from {start} in {name}")
        return {"Output": numbered}

    return build



def _run_all(conversion: Conversion) -> None:
    """A workflow running every recipe in order, as running the Alteryx workflow makes every output."""
    from api_gateway.conversions.model import run_in_order

    made = run_in_order(conversion, key="workflow:run", name=f"Run {conversion.title.removeprefix('the ')}",
                        description=f"Runs every recipe converted from {conversion.title}, each after the recipes "
                                    "it reads.")
    if made is not None:
        conversion.workflows.append(made[0])
