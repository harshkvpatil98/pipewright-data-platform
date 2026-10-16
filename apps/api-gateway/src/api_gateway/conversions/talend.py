"""A Talend job (.item) to recipes and a workflow (E2, X3).

Read as Talend saves a job: ``node``s (components, each with its
``elementParameter`` settings and its schema in ``metadata``) and
``connection``s (rows between components, and triggers between subjobs).
Each output (a file or a table written) becomes a recipe of the components
before it (``flows.py``); an input file is a dataset the project has,
matched by its file's name, and a database input's query is read by the SQL
step's translator. The job becomes a workflow running each subjob's recipes
in the order its OnSubjobOk and OnSubjobError triggers give.

Components converted: tFileInputDelimited and the database inputs (a query
written in), tMap (variables, lookups that join as Talend matches them:
unique match keeps the last row of a key, first match the first, all
matches every one, and two empty keys match, as Java's equals says; output
filters), tFilterRow (its conditions or its advanced condition), tSortRow,
tAggregateRow (ignoring empty values), tUniqRow (its unique rows), tUnite,
tReplicate and tLogRow, which change no rows, and the file and database
outputs.

Expressions are Java, read as Java runs them: text + an empty value is text
and "null", a whole number divided by a whole number is a whole number
toward zero, ``==`` on objects compares identity and is converted only
against a number written in, and String.trim removes characters up to a
space. A method or a routine not in the help's list (Math.round, which
rounds a half up toward positive infinity, among them) is refused.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import UNKNOWN, timestamp

from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr, Literal

from api_gateway.conversions import expressions as ex
from api_gateway.conversions.expressions import FALSE, NULL, TRUE, Language, Parser, call
from api_gateway.conversions.flows import (
    Component,
    Flow,
    Stream,
    derive,
    distinct,
    join,
    keep_rows,
    rename,
    select,
    sort,
    sql,
)
from api_gateway.conversions.model import Conversion, LinkPlan, NotConverted, run_in_order
from api_gateway.conversions.sql import Scope, compile_model, dataset_table, parse
from api_gateway.conversions.xmlfiles import attribute, children, local, read_xml

_TYPES: dict[str, PWType] = {
    "id_Integer": INT64, "id_Long": INT64, "id_Short": INT64, "id_Byte": INT64, "id_Double": FLOAT64,
    "id_Float": FLOAT64, "id_BigDecimal": FLOAT64, "id_String": STRING, "id_Character": STRING,
    "id_Boolean": BOOLEAN, "id_Date": timestamp(),
}
_WHOLE_TYPES = {"id_Integer", "id_Long", "id_Short", "id_Byte"}


# ============================================================ expressions


def _plus(parser: Parser, a: Expr, b: Expr) -> Expr:
    if parser.is_text(a) or parser.is_text(b):
        other = b if parser.is_text(a) else a
        if not (parser.is_text(a) and parser.is_text(b)):
            raise parser.refuse(f"+ joins text with a {parser.kind(other).value}, which Java writes by its own "
                                "rules (1.0, 1E10); this converts text + text.")

        def written(side: Expr) -> Expr:
            # Java writes an empty value as the text "null".
            return side if ex.never_empty(side) else call("coalesce", side, Literal("null", STRING))

        return call("concat", written(a), written(b))
    if parser.is_number(a) and parser.is_number(b):
        return call("add", a, b)
    raise parser.refuse("+ adds numbers or joins texts; this cannot tell which here.")


def _arithmetic(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        if not (parser.is_number(a) and parser.is_number(b)):
            raise parser.refuse("arithmetic here is on numbers.")
        if name == "div" and parser.is_whole(a) and parser.is_whole(b):
            # Java divides whole numbers to a whole number, toward zero.
            return call("trunc", call("div", a, b))
        return call(name, a, b)

    return build


def _identity(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        numbers = (isinstance(a, Literal) and isinstance(a.value, (int, float))) or (
            isinstance(b, Literal) and isinstance(b.value, (int, float)))
        if isinstance(b, Literal) and b.value is None:
            return call("is_null" if name == "eq" else "is_not_null", a)
        if isinstance(a, Literal) and a.value is None:
            return call("is_null" if name == "eq" else "is_not_null", b)
        if not numbers or parser.is_text(a) or parser.is_text(b):
            raise parser.refuse("== on objects compares which object it is, not the value; this converts == "
                                "against a number written in, or null. Use .equals() for text.")
        return call(name, a, b)

    return build


def _cast(parser: Parser, token) -> Expr | None:
    """A Java cast: (int) x, (double) x."""
    if token.kind != "(":
        return None
    following = parser.tokens[parser.index + 1]
    after = parser.tokens[parser.index + 2]
    if following.kind != "name" or after.kind != ")" or following.text not in (
            "int", "long", "double", "float", "Integer", "Long", "Double", "String"):
        return None
    parser.advance()
    kind = parser.advance().text
    parser.expect(")")
    value = parser.unary()
    if kind in ("double", "float", "Double") and parser.is_number(value):
        return value
    if kind in ("int", "long", "Integer", "Long") and parser.is_whole(value):
        return value
    if kind in ("int", "long") and parser.is_number(value):
        return call("trunc", value)  # Java casts a double to an int toward zero
    raise parser.refuse(f"({kind}) of a {parser.kind(value).value} is a change this does not convert.")


_METHODS = {"toUpperCase": ("upper", 0), "toLowerCase": ("lower", 0), "length": ("length", 0)}


def _method(parser: Parser, target: Expr, name: str, args: list[Expr]) -> Expr:
    if name in _METHODS:
        ir, count = _METHODS[name]
        if len(args) != count:
            raise parser.refuse(f".{name}() takes {count} arguments.")
        return call(ir, target)
    if name == "trim" and not args:
        return call("regex_replace", target, Literal("^[\\x00-\\x20]+|[\\x00-\\x20]+$", STRING),
                    Literal("", STRING))
    if name in ("equals", "equalsIgnoreCase") and len(args) == 1:
        a, b = (target, args[0]) if name == "equals" else (call("lower", target), call("lower", args[0]))
        # A null argument is never equal; a null receiver stops the job.
        return ex.two_valued(call("eq", a, b))
    if name in ("contains", "startsWith", "endsWith") and len(args) == 1:
        needle = ex.text_literal(parser, args[0], f"What .{name}() looks for")
        ir = {"contains": "contains", "startsWith": "starts_with", "endsWith": "ends_with"}[name]
        return call(ir, target, Literal(needle, STRING))
    if name == "substring" and len(args) in (1, 2):
        begin = ex.whole_literal(parser, args[0], ".substring()'s start")
        if len(args) == 2:
            end = ex.whole_literal(parser, args[1], ".substring()'s end")
            return call("substring", target, Literal(begin + 1, INT64), Literal(end - begin, INT64))
        return call("substring", target, Literal(begin + 1, INT64))
    if name == "replace" and len(args) == 2:
        return call("replace", target, Literal(ex.text_literal(parser, args[0], ".replace()'s target"), STRING),
                    Literal(ex.text_literal(parser, args[1], ".replace()'s replacement"), STRING))
    if name == "isEmpty" and not args:
        return call("eq", call("length", target), Literal(0, INT64))
    raise parser.refuse(f".{name}() is not a Java method this converts.")


def _postfix(parser: Parser, left: Expr, token, minimum: int) -> Expr | None:
    if token.kind == "op" and token.text == "?" and minimum <= 5:
        parser.advance()
        yes = parser.expression(0)
        parser.expect("op", ":")
        return ex.iif(left, yes, parser.expression(5))
    if token.kind == "op" and token.text == ".":
        parser.advance()
        name = parser.expect("name").text
        args = parser.arguments() if parser.current.kind == "(" else None
        if args is None:
            raise parser.refuse(f".{name} reads a field of a value, which this does not convert.")
        return _method(parser, left, name, args)
    return None


def _special(parser: Parser, token) -> Expr | None:
    cast = _cast(parser, token)
    if cast is not None:
        return cast
    if token.kind == "name" and "." in token.text and parser.tokens[parser.index + 1].kind == "(":
        head, _, method = token.text.rpartition(".")
        if head not in _STATIC and head.split(".")[0] not in ("StringHandling", "Relational", "Mathematical", "Math",
                                                              "TalendDate", "Numeric", "TalendString"):
            # row1.name.toUpperCase(): a method of a column.
            parser.advance()
            target = parser.column(head, token.at)
            return _method(parser, target, method, parser.arguments())
    return None


def _static(name: str, ir: str, count: int):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        if len(args) != count:
            raise parser.refuse(f"{name} takes {count} arguments.")
        return call(ir, *args)

    return build


def _refused(name: str, reason: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        raise parser.refuse(f"{name} {reason}")

    return build


def _remainder(parser: Parser) -> Expr:
    raise parser.refuse("% is not converted here: this converts Java's arithmetic + - * and /.")


_STATIC = {
    "StringHandling.UPCASE": _static("StringHandling.UPCASE", "upper", 1),
    "StringHandling.DOWNCASE": _static("StringHandling.DOWNCASE", "lower", 1),
    "StringHandling.LEN": _static("StringHandling.LEN", "length", 1),
    "Relational.ISNULL": _static("Relational.ISNULL", "is_null", 1),
    "Mathematical.ABS": _static("Mathematical.ABS", "abs", 1), "Math.abs": _static("Math.abs", "abs", 1),
    "Math.floor": _static("Math.floor", "floor", 1), "Math.ceil": _static("Math.ceil", "ceil", 1),
    "Math.sqrt": _static("Math.sqrt", "sqrt", 1), "Math.pow": _static("Math.pow", "power", 2),
    "Math.round": _refused("Math.round", "rounds a half up toward positive infinity (-2.5 is -2), which no formula "
                                         "here does; it is not converted."),
    "TalendDate.getCurrentDate": _refused("TalendDate.getCurrentDate", "reads the clock of the job's machine."),
    "TalendDate.formatDate": _refused("TalendDate.formatDate", "formats by Java's patterns, which this does not "
                                                               "convert."),
}

JAVA = Language(
    name="Java",
    infix={"||": (10, lambda p, a, b: call("or", a, b)), "&&": (20, lambda p, a, b: call("and", a, b)),
           "==": (30, _identity("eq")), "!=": (30, _identity("ne")),
           "<": (35, lambda p, a, b: call("lt", a, b)), "<=": (35, lambda p, a, b: call("le", a, b)),
           ">": (35, lambda p, a, b: call("gt", a, b)), ">=": (35, lambda p, a, b: call("ge", a, b)),
           "+": (50, _plus), "-": (50, _arithmetic("sub")), "*": (60, _arithmetic("mul")),
           "/": (60, _arithmetic("div")), "%": (60, lambda p, a, b: _remainder(p))},
    prefix={"!": (70, lambda p, a: call("not", a)), "-": (70, lambda p, a: call("neg", a))},
    functions=_STATIC,
    constants={"true": TRUE, "false": FALSE, "null": NULL},
    bare_columns=True,
    special=_special,
    postfix=_postfix,
    case_sensitive_names=True,
)
_OPERATORS = ("==", "!=", "<=", ">=", "&&", "||", "<", ">", "+", "-", "*", "/", "%", "!", "?", ":", ".")


def java(text: str, columns: dict[str, PWType], names: dict[str, str], what: str) -> Expr:
    """A Java expression over qualified names (row1.amount, Var.tax), as IR over the working columns."""
    if re.search(r"\bcontext\.|globalMap", text):
        raise NotConverted(f"{what} reads a context variable or the globalMap, whose value this does not know.")
    qualified = {name: columns[working] for name, working in names.items() if working in columns}
    tree = ex.parse(text.strip().rstrip(";"), JAVA, qualified, what=what, quotes='"', escape="backslash",
                    brackets=False, operators=_OPERATORS, name_extra="_.")
    return _renamed(tree, names)


def _renamed(expr: Expr, names: dict[str, str]) -> Expr:
    if isinstance(expr, Column):
        return Column(names.get(expr.name, expr.name))
    if isinstance(expr, Call):
        return Call(expr.name, tuple(_renamed(arg, names) for arg in expr.args))
    if isinstance(expr, Case):
        return Case(tuple((_renamed(c, names), _renamed(v, names)) for c, v in expr.branches),
                    _renamed(expr.default, names) if expr.default is not None else None)
    if isinstance(expr, Cast):
        return Cast(_renamed(expr.value, names), expr.to)
    return expr


# ==================================================================== the job


@dataclass
class _Node:
    name: str
    component: str
    element: object
    parameters: dict[str, str]

    def value(self, name: str, default: str = "") -> str:
        """A setting, as a value: a Java text written in loses its quotes."""
        raw = self.parameters.get(name, default)
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"') and '"' not in raw[1:-1]:
            return raw[1:-1]
        return raw

    def table(self, name: str) -> list[dict[str, str]]:
        """A table setting: its rows, each a dict of its columns."""
        for parameter in children(self.element, "elementParameter"):
            if attribute(parameter, "name") == name:
                rows, row = [], {}
                for item in children(parameter, "elementValue"):
                    column = attribute(item, "elementRef") or ""
                    if column in row:
                        rows.append(row)
                        row = {}
                    row[column] = attribute(item, "value") or ""
                if row:
                    rows.append(row)
                return rows
        return []

    def schema(self, connector: str = "FLOW") -> list[tuple[str, str]]:
        for metadata in children(self.element, "metadata"):
            if (attribute(metadata, "connector") or "FLOW") == connector:
                return [(attribute(c, "name") or "", attribute(c, "type") or "") for c in children(metadata, "column")]
        return []


def convert_talend(files: dict[str, bytes], lookup) -> Conversion:
    (file_name, data), = files.items()
    root = read_xml(data, file_name)
    if local(root.tag) != "ProcessType":
        raise NotConverted(f"{file_name} is not a Talend job (its root is {local(root.tag)}, not ProcessType).")
    title = posixpath.splitext(posixpath.basename(file_name))[0].rsplit("_", 1)[0] or "job"
    conversion = Conversion(format="talend", title=f"the Talend job {title}")
    nodes: dict[str, _Node] = {}
    for element in children(root, "node"):
        parameters = {attribute(p, "name") or "": attribute(p, "value") or "" for p in
                      children(element, "elementParameter")}
        name = parameters.get("UNIQUE_NAME", "")
        nodes[name] = _Node(name, attribute(element, "componentName") or "", element, parameters)
    data_links: list[tuple[str, str, str, str]] = []  # source, target, connector, label
    triggers: list[tuple[str, str, str]] = []
    for connection in children(root, "connection"):
        source, target = attribute(connection, "source") or "", attribute(connection, "target") or ""
        connector = attribute(connection, "connectorName") or ""
        label = attribute(connection, "label") or attribute(connection, "metaname") or connector
        if connector in ("SUBJOB_OK", "SUBJOB_ERROR", "COMPONENT_OK", "COMPONENT_ERROR", "RUN_IF", "ITERATE"):
            triggers.append((source, target, connector))
        else:
            data_links.append((source, target, connector, label))
    flow = Flow(conversion, title, f"talend:{title}")
    reader = _Reader(flow, nodes, data_links, lookup, conversion)
    for node in nodes.values():
        label = f"{node.component} {node.name}"
        section = conversion.section(f"{file_name}: {label}")
        inputs = {f"{connector}:{link_label}": (source, link_label) for source, target, connector, link_label in
                  data_links if target == node.name}
        writes = reader.writes(node)
        flow.add(Component(node.name, label, inputs, reader.build(node, label), section, writes=writes))
    flow.outputs()
    flow.unused()
    for component in flow.components.values():
        if not component.section.entries:
            component.section.converted(component.label, "Its steps are in the recipes of the outputs after it")
    _workflow(conversion, title, nodes, data_links, triggers, file_name)
    conversion.notes.append("The job is read, never run: no Java of it ran here.")
    return conversion


def _workflow(conversion: Conversion, title: str, nodes, data_links, triggers, file_name: str) -> None:
    """The job's recipes, a subjob after the subjobs its triggers follow."""
    # A subjob is the components joined by rows; name each by its first component.
    group: dict[str, str] = {name: name for name in nodes}

    def find(name: str) -> str:
        while group[name] != name:
            name = group[name]
        return name

    for source, target, _, _ in data_links:
        if source in group and target in group:
            group[find(target)] = find(source)
    made = run_in_order(conversion, key="workflow:job", name=title,
                        description=f"The Talend job {title}: each subjob's recipes, after the subjobs its "
                                    "triggers follow.")
    if made is None:
        return
    plan, task_of = made
    # An output's recipe is in its component's subjob; a recipe made for a branch, in the subjob of what reads it.
    subjob_of: dict[str, str] = {}
    for recipe in conversion.recipes:
        component = recipe.key.split(":", 2)[-1] if recipe.key.startswith(f"talend:{title}:") else None
        if component in group:
            subjob_of[recipe.key] = find(component)
    for _ in range(len(conversion.recipes)):
        for recipe in conversion.recipes:
            for read in recipe.reads_all():
                if recipe.key in subjob_of and read not in subjob_of and read in task_of:
                    subjob_of[read] = subjob_of[recipe.key]
    by_subjob: dict[str, list[str]] = {}
    for key, subjob in subjob_of.items():
        if key in task_of:
            by_subjob.setdefault(subjob, []).append(task_of[key])
    section = conversion.section(f"{file_name}: the job's triggers")
    for source, target, connector in triggers:
        a, b = find(source) if source in group else None, find(target) if target in group else None
        condition = {"SUBJOB_OK": "on_success", "SUBJOB_ERROR": "on_failure"}.get(connector)
        subject = f"{connector} from {source} to {target}"
        if condition is None:
            section.not_converted(subject, "A trigger on one component, a condition or a loop is not converted; "
                                           "OnSubjobOk and OnSubjobError are.")
            continue
        if a not in by_subjob or b not in by_subjob:
            section.not_converted(subject, "One of its subjobs has no recipe here, so it links nothing.")
            continue
        for x in by_subjob[a]:
            for y in by_subjob[b]:
                plan.links.append(LinkPlan(x, y, condition))
        section.converted(subject, f"The workflow runs the second subjob {'after' if condition == 'on_success' else 'when'} "
                                   f"the first {'succeeds' if condition == 'on_success' else 'fails'}")
    conversion.workflows.append(plan)


class _Reader:
    def __init__(self, flow: Flow, nodes, data_links, lookup, conversion: Conversion) -> None:
        self.flow = flow
        self.nodes = nodes
        self.data_links = data_links
        self.lookup = lookup
        self.conversion = conversion

    def writes(self, node: _Node) -> str | None:
        if node.component in ("tFileOutputDelimited", "tFileOutputExcel", "tFileOutputCSV"):
            path = node.value("FILENAME").replace("\\", "/")
            return posixpath.splitext(posixpath.basename(path))[0] or node.name
        if re.fullmatch(r"t\w*Output", node.component) and node.component not in ("tLogRow",):
            return node.value("TABLE") or node.name
        return None

    def build(self, node: _Node, label: str):
        component = node.component
        if component == "tFileInputDelimited":
            return lambda flow, inputs: self.file_input(node, label)
        if re.fullmatch(r"t\w*Input", component) and component != "tFileInputDelimited":
            return lambda flow, inputs: self.database_input(node, label)
        builders = {"tMap": self.tmap, "tFilterRow": self.filter_row, "tSortRow": self.sort_row,
                    "tAggregateRow": self.aggregate_row, "tUniqRow": self.uniq_row, "tUnite": self.unite,
                    "tReplicate": self.replicate, "tLogRow": self.replicate}
        if component in builders:
            return lambda flow, inputs: builders[component](node, inputs, label)
        if self.writes(node):
            return lambda flow, inputs: self.output(node, inputs, label)
        reasons = {"tJava": "It runs Java code, which this reads and never runs.",
                   "tJavaRow": "It runs Java code on each row, which this reads and never runs.",
                   "tJavaFlex": "It runs Java code, which this reads and never runs.",
                   "tRunJob": "It runs another job, which this upload does not hold."}
        return _not(reasons.get(component, f"{component} is not a component this converts."))

    def links_into(self, node: _Node) -> list[tuple[str, str, str]]:
        return [(source, connector, label) for source, target, connector, label in self.data_links
                if target == node.name]

    def one(self, inputs: dict[str, Stream]) -> Stream:
        if not inputs:
            raise NotConverted("Nothing is connected to its input.")
        return next(iter(inputs.values()))

    def outputs_of(self, node: _Node, stream: Stream) -> dict:
        """The same rows on every row connection out of a component, by its label."""
        labels = [label for source, _, _, label in self.data_links if source == node.name]
        return {label: stream for label in labels} or {"out": stream}

    # ----------------------------------------------------------- inputs

    def declared(self, node: _Node) -> list[tuple[str, str]]:
        schema = node.schema()
        if not schema:
            raise NotConverted("It has no schema.")
        return schema

    def file_input(self, node: _Node, label: str) -> dict:
        path = node.value("FILENAME")
        if not path or "+" in path or "context." in path:
            raise NotConverted("Its file is worked out by code (a context variable), whose value this does not "
                               "know.")
        name = posixpath.splitext(posixpath.basename(path.replace("\\", "/")))[0]
        schema = self.declared(node)
        need = self.conversion.need(f"file:{name.lower()}", name, f"the file {posixpath.basename(path)}",
                                    columns=[c for c, _ in schema], types={c: _TYPES.get(t, UNKNOWN) for c, t in schema})
        found = self.lookup(need)
        if found is None:
            raise NotConverted(f"It reads {posixpath.basename(path)}. Choose the dataset that holds it (none here is "
                               f"called “{name}”), then read the job again.")
        stream = self.typed(Stream(need.key, [], dict(found)), schema)
        self.flow.converted(self.flow.labelled(label), f"Reads the dataset “{name}”")
        return self.outputs_of(node, stream)

    def typed(self, stream: Stream, schema: list[tuple[str, str]]) -> Stream:
        by_lower = {c.lower(): c for c in stream.columns}
        missing = [c for c, _ in schema if c.lower() not in by_lower]
        if missing:
            raise NotConverted(f"The dataset has no column {missing[0]}.")
        stream = select(stream, [by_lower[c.lower()] for c, _ in schema], "Keep the schema's columns")
        return rename(stream, {by_lower[c.lower()]: c for c, _ in schema}, "Name them as the schema does")

    def database_input(self, node: _Node, label: str) -> dict:
        query = node.value("QUERY").strip()
        if not query:
            raise NotConverted("It has no query.")
        query = query.replace('\\"', '"').strip('"').replace("\\n", " ")
        from sqlglot import exp

        statement = parse(query, f"The query of {node.name}")
        tables = {}
        for table in statement.find_all(exp.Table):
            need = self.conversion.need(f"table:{table.name.lower()}", table.name, f"the table {table.sql()}")
            found = self.lookup(need)
            if found is None:
                raise NotConverted(f"Its query reads {table.sql()}. Choose the dataset that holds it, then read the "
                                   "job again.")
            full = ".".join(p for p in (table.catalog, table.db, table.name) if p)
            tables[full] = tables[table.name] = dataset_table(table.name, need.key, found)
        chain, compiler = compile_model(statement, scope=Scope(tables=tables), owner=node.name,
                                        owner_key=f"talend-sql:{node.name}", parameters={})
        self.conversion.recipes.extend(compiler.helpers)
        stream = self.typed(Stream(chain.base, chain.steps, chain.columns, chain.lines), self.declared(node))
        self.flow.converted(self.flow.labelled(label), "Runs its query: " + "; ".join(chain.lines))
        return self.outputs_of(node, stream)

    # ------------------------------------------------------------- tMap

    def tmap(self, node: _Node, inputs: dict[str, Stream], label: str) -> dict:
        data = next((item for item in node.element if local(item.tag) == "nodeData"), None)
        if data is None:
            raise NotConverted("Its mapping is not in the file.")
        input_tables = [t for t in data if local(t.tag) == "inputTables"]
        if not input_tables:
            raise NotConverted("It has no input.")
        by_label = {key.split(":", 1)[1]: stream for key, stream in inputs.items()}
        main = input_tables[0]
        main_name = attribute(main, "name") or ""
        if main_name not in by_label:
            raise NotConverted(f"Its main input {main_name} is not connected.")
        stream = by_label[main_name]
        names = {f"{main_name}.{column}": column for column in stream.columns}
        lines = []
        for table in input_tables[1:]:
            stream, names, line = self.lookup_join(node, table, stream, names, by_label)
            lines.append(line)
        # Variables, in order: each may read the ones before it.
        for table in (t for t in data if local(t.tag) == "varTables"):
            for entry in children(table, "mapperTableEntries"):
                variable = attribute(entry, "name") or ""
                text = attribute(entry, "expression") or ""
                working = _unique(f"Var__{variable}", stream.columns)
                stream = derive(stream, working, java(text, stream.columns, names, f"The variable {variable}"),
                                f"Work out the variable {variable} = {text}")
                names[f"{attribute(table, 'name') or 'Var'}.{variable}"] = working
                lines.append(f"Var.{variable} = {text}")
        outputs = {}
        for table in (t for t in data if local(t.tag) == "outputTables"):
            output_name = attribute(table, "name") or ""
            if (attribute(table, "reject") or "false") == "true" or (attribute(table, "rejectInnerJoin") or
                                                                     "false") == "true":
                raise NotConverted(f"Its output {output_name} takes rejected rows, which this does not convert.")
            out = stream
            if (attribute(table, "activateExpressionFilter") or "false") == "true" and attribute(table,
                                                                                                 "expressionFilter"):
                text = attribute(table, "expressionFilter") or ""
                out = keep_rows(out, java(text, out.columns, names, f"The filter of {output_name}"),
                                f"Keep the rows where {text} ({output_name})")
                lines.append(f"{output_name}: keep where {text}")
            final = []
            for entry in children(table, "mapperTableEntries"):
                column = attribute(entry, "name") or ""
                text = attribute(entry, "expression") or ""
                working = _unique(f"{output_name}__{column}", out.columns)
                value = java(text, out.columns, names, f"The column {column} of {output_name}")
                whole = Parser([], JAVA, out.columns, "").is_whole(value) or (
                    isinstance(value, Call) and value.name == "trunc")
                if (attribute(entry, "type") or "") in _WHOLE_TYPES and not whole:
                    raise NotConverted(f"The column {column} of {output_name} is whole, and its expression is not.")
                out = derive(out, working, value, f"Work out {column} = {text} ({output_name})")
                final.append((working, column))
            out = select(out, [w for w, _ in final], f"Keep {output_name}'s columns")
            outputs[output_name] = rename(out, dict(final), f"Name them as {output_name} does")
            lines.append(f"{output_name}: " + ", ".join(column for _, column in final))
        self.flow.converted(self.flow.labelled(label), lines)
        return outputs

    def lookup_join(self, node: _Node, table, stream: Stream, names: dict[str, str], by_label: dict[str, Stream]):
        lookup_name = attribute(table, "name") or ""
        if lookup_name not in by_label:
            raise NotConverted(f"Its lookup {lookup_name} is not connected.")
        other = by_label[lookup_name]
        if (attribute(table, "lookupMode") or "LOAD_ONCE") not in ("LOAD_ONCE", ""):
            raise NotConverted(f"Its lookup {lookup_name} reloads at each row, which this does not convert.")
        if (attribute(table, "activateExpressionFilter") or "false") == "true":
            raise NotConverted(f"Its lookup {lookup_name} has a filter, which this does not convert.")
        keys = [(attribute(e, "name") or "", attribute(e, "expression") or "")
                for e in children(table, "mapperTableEntries") if attribute(e, "expression")]
        if not keys:
            raise NotConverted(f"Its lookup {lookup_name} has no key: every row with every row, which this does not "
                               "convert.")
        on, right_on = [], []
        for column, text in keys:
            value = java(text, stream.columns, names, f"The key {column} of {lookup_name}")
            if isinstance(value, Column):
                on.append(value.name)
            else:
                working = _unique(f"{lookup_name}__key_{column}", stream.columns)
                stream = derive(stream, working, value, f"Work out the key {column} = {text}")
                on.append(working)
            right_on.append(column)
        matching = attribute(table, "matchingMode") or "UNIQUE_MATCH"
        if matching in ("UNIQUE_MATCH", "FIRST_MATCH"):
            # A unique match keeps the last row of a key; a first match, the first.
            other = distinct(other, right_on, f"Keep the {'last' if matching == 'UNIQUE_MATCH' else 'first'} row of "
                                              f"each {', '.join(right_on)} ({lookup_name})",
                             keep="last" if matching == "UNIQUE_MATCH" else "first")
        elif matching != "ALL_MATCHES":
            raise NotConverted(f"Its lookup {lookup_name} matches by {matching}, which this does not convert.")
        key, columns = self.flow.dataset(other, f"{node.name} lookup {lookup_name}")
        how = "inner" if (attribute(table, "innerJoin") or "false") == "true" else "left"
        suffix = f"__{lookup_name}"
        joined = join(stream, key, columns, how=how, on=on, right_on=right_on, bring=list(columns), suffix=suffix,
                      empty_keys="match each other",
                      line=f"Look up {lookup_name} on {', '.join(right_on)} ({'inner join' if how == 'inner' else 'left'}"
                           f", {matching.lower().replace('_', ' ')})")
        for column in columns:
            names[f"{lookup_name}.{column}"] = column if column not in stream.columns else f"{column}{suffix}"
        return joined, names, f"Look up {lookup_name} on {', '.join(right_on)}"

    # ------------------------------------------------------ the others

    def filter_row(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        names = {f"input_row.{column}": column for column in stream.columns}
        if node.value("USE_ADVANCED", "false") == "true":
            text = node.value("ADVANCED_COND")
            condition = java(text, stream.columns, names, "The advanced condition")
            words = text
        else:
            parts = []
            for row in node.table("CONDITIONS"):
                column, operator, value = row.get("INPUT_COLUMN", ""), row.get("OPERATOR", ""), row.get("RVALUE", "")
                if row.get("FUNCTION"):
                    raise NotConverted(f"Its condition on {column} applies {row['FUNCTION']}, which this does not "
                                       "convert.")
                if operator not in ("==", "!=", "<", "<=", ">", ">="):
                    raise NotConverted(f"Its condition on {column} uses {operator}, which this does not convert.")
                parts.append(f"input_row.{column} {operator} {value}" if operator not in ("==", "!=") or
                             not value.startswith('"') else
                             f"{'!' if operator == '!=' else ''}input_row.{column}.equals({value})")
            if not parts:
                raise NotConverted("It has no condition.")
            joiner = " && " if node.value("LOGICAL_OP", "&&") in ("&&", "AND") else " || "
            words = joiner.join(parts)
            condition = java(words, stream.columns, names, "The conditions")
        self.flow.converted(self.flow.labelled(label), f"Keep the rows where {words} (FILTER); the rest (REJECT)")
        labels = {connector: link_label for source, _, connector, link_label in
                  ((s, t, c, lbl) for s, t, c, lbl in self.data_links if s == node.name)}
        return {labels.get("FILTER", "FILTER"): keep_rows(stream, condition, f"Keep the rows where {words}"),
                labels.get("REJECT", "REJECT"): keep_rows(stream, condition, f"Keep the rows where {words} is not "
                                                                             "true", keep=False)}

    def sort_row(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        keys = []
        for row in node.table("CRITERIA"):
            column = row.get("COLNAME", "")
            ascending = row.get("ORDER", "asc").lower() == "asc"
            if row.get("SORT", "num") == "date":
                raise NotConverted(f"It sorts {column} as a date read from text, which this does not convert.")
            keys.append((column, ascending, ascending))
        if not keys:
            raise NotConverted("It sorts by nothing.")
        self.flow.converted(self.flow.labelled(label), "Sort by " + ", ".join(
            f"{k} {'ascending' if a else 'descending'}" for k, a, _ in keys),
            ["Talend's help does not say where an empty value sorts; here it comes first in ascending order, as "
             "a Java comparator that treats null as the least puts it."])
        return self.outputs_of(node, sort(stream, keys, f"Sort ({node.name})"))

    def aggregate_row(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        groups = [(row.get("OUTPUT_COLUMN", ""), row.get("INPUT_COLUMN", "")) for row in node.table("GROUPBYS")]
        items = [f"{_q(source)} AS {_q(out)}" if out != source else _q(source) for out, source in groups]
        for row in node.table("OPERATIONS"):
            out, function, source = row.get("OUTPUT_COLUMN", ""), row.get("FUNCTION", ""), row.get("INPUT_COLUMN", "")
            ignoring = row.get("IGNORE_NULL", "false") == "true"
            if source not in stream.columns:
                raise NotConverted(f"It summarises {source}, which the rows coming in do not have.")
            if function == "count":
                items.append(f"{'COUNT(' + _q(source) + ')' if ignoring else 'COUNT(*)'} AS {_q(out)}")
                continue
            if function == "distinct" or function == "count_distinct":
                items.append(f"COUNT(DISTINCT {_q(source)}) AS {_q(out)}")
                continue
            if function not in ("sum", "min", "max", "avg"):
                raise NotConverted(f"Its {function} of {source} is not a summary this converts (sum, count, min, max, "
                                   "avg and count distinct are).")
            if not ignoring:
                raise NotConverted(f"Its {function} of {source} does not ignore empty values, which stops the job on "
                                   "one; tick Ignore null values and convert again.")
            items.append(f"{function.upper()}({_q(source)}) AS {_q(out)}")
        text = f"SELECT {', '.join(items)} FROM input" + (
            f" GROUP BY {', '.join(_q(source) for _, source in groups)}" if groups else "")
        self.flow.converted(self.flow.labelled(label), f"Summarise: {', '.join(items)}")
        return self.outputs_of(node, sql(stream, text, f"Summarise ({node.name})"))

    def uniq_row(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        keys = [row.get("SCHEMA_COLUMN", "") for row in node.table("UNIQUE_KEY")
                if row.get("KEY_ATTRIBUTE", "false") == "true"]
        if any(row.get("CASE_SENSITIVE", "true") == "false" for row in node.table("UNIQUE_KEY")
               if row.get("KEY_ATTRIBUTE", "false") == "true"):
            raise NotConverted("It compares a key without regard to case, which this does not convert.")
        if not keys:
            raise NotConverted("It has no key.")
        labels = {connector: link_label for source, _, connector, link_label in self.data_links
                  if source == node.name}
        if "DUPLICATE" in labels:
            raise NotConverted("Its duplicates output is used, which this does not convert.")
        self.flow.converted(self.flow.labelled(label), f"Keep the first row of each {', '.join(keys)}")
        return {labels.get("UNIQUE", "UNIQUE"): distinct(stream, keys, f"Keep the first row of each "
                                                                       f"{', '.join(keys)}")}

    def unite(self, node: _Node, inputs, label) -> dict:
        streams = list(inputs.values())
        if len(streams) < 2:
            raise NotConverted("It has fewer than two inputs.")
        stream = streams[0]
        for index, other in enumerate(streams[1:], start=2):
            if list(other.columns) != list(stream.columns):
                raise NotConverted(f"Its input {index} has other columns than its first.")
            key, _ = self.flow.dataset(other, f"{node.name} input {index}")
            stream = stream.then({"step_type": "union_datasets", "config": {
                "other_dataset_id": {"$dataset": key}, "deduplicate": False, "column_strategy": "strict"}},
                f"Add the rows of input {index} ({node.name})", columns=dict(stream.columns))
        self.flow.converted(self.flow.labelled(label), f"Add the rows of {len(streams)} inputs together")
        return self.outputs_of(node, stream)

    def replicate(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        words = "Prints the rows and passes them on" if node.component == "tLogRow" else \
            "Gives the same rows to each of its outputs"
        self.flow.converted(self.flow.labelled(label), words)
        return self.outputs_of(node, stream)

    def output(self, node: _Node, inputs, label) -> dict:
        stream = self.one(inputs)
        schema = node.schema()
        if schema:
            missing = [c for c, _ in schema if c not in stream.columns]
            if missing:
                raise NotConverted(f"It writes {missing[0]}, which the rows coming in do not have.")
            stream = select(stream, [c for c, _ in schema], "Keep the columns it writes")
        return {"out": stream}


def _unique(name: str, taken) -> str:
    candidate, number = name, 2
    while candidate in taken:
        candidate, number = f"{name}_{number}", number + 1
    return candidate


def _not(reason: str):
    def build(flow: Flow, inputs) -> dict:
        raise NotConverted(reason)

    return build


def _q(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'

