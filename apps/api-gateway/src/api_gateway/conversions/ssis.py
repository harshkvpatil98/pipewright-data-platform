"""An SSIS package (.dtsx) to recipes and a workflow (E2, X3).

Read as Microsoft publishes the package format: the package's executables
and the precedence constraints between them, and in each Data Flow task a
pipeline of components joined by paths, their columns tied together by
lineage. Each destination becomes a recipe of the components before it
(``flows.py``); a source is a dataset the project has (a flat file matched by
its file's name, a table by its name), or a SQL command read by the SQL
step's translator. The package becomes a workflow running each data flow's
recipes in the order its precedence constraints give (success, failure and
completion).

Components converted: Flat File, OLE DB and Excel sources and destinations,
Derived Column, Conditional Split (first match wins; the default output
takes the rest), Sort (without removing duplicates), Aggregate (the
documented aggregation types), Merge Join (inner, left and full, with
TreatNullsAsEqual), Union All, Multicast and Row Count, which change no
rows.

Expressions follow Microsoft's published rules: an operator with a NULL
gives NULL, and so does ``?:`` when its condition is NULL; TRIM, LTRIM and
RTRIM remove spaces only. A cast that changes a value (a number to text, a
decimal to a whole number), ROUND (whose tie rule is not documented) and
anything reading a variable are refused, not guessed.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import UNKNOWN, timestamp

from service_transformations.formula.printer import if_chain
from service_transformations.ir.expressions import Expr, Literal

from api_gateway.conversions import expressions as ex
from api_gateway.conversions.expressions import FALSE, NULL, TRUE, Language, Parser, call
from api_gateway.conversions.flows import (
    Component,
    Flow,
    Stream,
    derive,
    join,
    keep_rows,
    rename,
    select,
    sort,
    sql,
)
from api_gateway.conversions.model import Conversion, LinkPlan, NotConverted
from api_gateway.conversions.sql import Scope, compile_model, dataset_table, parse
from api_gateway.conversions.xmlfiles import attribute, child, children, descendants, local, read_xml

_TYPES: dict[str, PWType] = {
    "i1": INT64, "i2": INT64, "i4": INT64, "i8": INT64, "ui1": INT64, "ui2": INT64, "ui4": INT64, "ui8": INT64,
    "r4": FLOAT64, "r8": FLOAT64, "numeric": FLOAT64, "decimal": FLOAT64, "cy": FLOAT64, "str": STRING,
    "wstr": STRING, "text": STRING, "ntext": STRING, "bool": BOOLEAN, "dbDate": DATE, "date": DATE,
    "dbTimeStamp": timestamp(), "dbTimeStamp2": timestamp(),
}
_NUMBER_CASTS = {"DT_R4", "DT_R8", "DT_I1", "DT_I2", "DT_I4", "DT_I8", "DT_UI1", "DT_UI2", "DT_UI4", "DT_UI8"}
_TEXT_CASTS = {"DT_STR", "DT_WSTR", "DT_TEXT", "DT_NTEXT"}


# ============================================================ expressions


def _plus(parser: Parser, a: Expr, b: Expr) -> Expr:
    if parser.is_text(a) and parser.is_text(b):
        return call("concat", a, b)
    if parser.is_number(a) and parser.is_number(b):
        return call("add", a, b)
    raise parser.refuse("+ joins two texts or adds two numbers; this cannot tell which here, or it mixes them.")


def _arithmetic(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        if not (parser.is_number(a) and parser.is_number(b)):
            raise parser.refuse("arithmetic here is on numbers.")
        if name == "mod":
            raise parser.refuse("% gives a remainder whose sign for every value the reference does not give.")
        if name == "div" and parser.is_whole(a) and parser.is_whole(b):
            # Whole numbers divide to a whole number, toward zero, as in .NET.
            return call("trunc", call("div", a, b))
        return call(name, a, b)

    return build


def _special(parser: Parser, token) -> Expr | None:
    """A cast: (DT_I4)expr, (DT_WSTR, 50)expr."""
    if token.kind != "(":
        return None
    following = parser.tokens[parser.index + 1]
    if following.kind != "name" or not following.text.upper().startswith("DT_"):
        return None
    parser.advance()
    kind = parser.advance().text.upper()
    while parser.current.kind == ",":
        parser.advance()
        parser.advance()
    parser.expect(")")
    value = parser.unary()
    if kind in _NUMBER_CASTS and parser.is_number(value):
        if kind.startswith(("DT_I", "DT_UI")) and not parser.is_whole(value):
            raise parser.refuse(f"({kind}) makes a decimal a whole number, by a rule this does not convert.")
        return value
    if kind in _TEXT_CASTS and parser.is_text(value):
        return value  # text stays text; one longer than its length stops the package, as it does here
    raise parser.refuse(f"({kind}) changes {parser.kind(value).value} to another kind, by rules (formats, regions) "
                        "this does not convert.")


def _postfix(parser: Parser, left: Expr, token, minimum: int) -> Expr | None:
    if token.kind == "op" and token.text == "?" and minimum <= 5:
        parser.advance()
        yes = parser.expression(0)
        parser.expect("op", ":")
        no = parser.expression(5)
        # A NULL condition gives NULL, as Microsoft's reference says.
        return if_chain([(call("is_null", left), NULL)], ex.iif(left, yes, no))
    return None


def _null(parser: Parser, args) -> Expr:
    return NULL


def _spaces(pattern: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        if len(args) != 1:
            raise parser.refuse("TRIM takes one text.")
        return call("regex_replace", args[0], Literal(pattern, STRING), Literal("", STRING))

    return build


def _fn(name: str, count: int, ir: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        if len(args) != count:
            raise parser.refuse(f"{name} takes {count} arguments.")
        return call(ir, *args)

    return build


def _substring(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) != 3:
        raise parser.refuse("SUBSTRING takes a text, a start and a length.")
    start = ex.whole_literal(parser, args[1], "SUBSTRING's start")
    length = ex.whole_literal(parser, args[2], "SUBSTRING's length")
    if start < 1 or length < 0:
        raise parser.refuse("SUBSTRING starts at 1, with a length of 0 or more.")
    return call("substring", args[0], Literal(start, INT64), Literal(length, INT64))


def _count(parser: Parser, args: list[Expr], name: str, ir: str) -> Expr:
    if len(args) != 2:
        raise parser.refuse(f"{name} takes a text and a count.")
    return call(ir, args[0], Literal(ex.whole_literal(parser, args[1], f"{name}'s count"), INT64))


def _refused(name: str, reason: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        raise parser.refuse(f"{name} {reason}")

    return build


SSIS = Language(
    name="SSIS",
    infix={"||": (10, lambda p, a, b: call("or", a, b)), "&&": (20, lambda p, a, b: call("and", a, b)),
           "==": (30, lambda p, a, b: call("eq", a, b)), "!=": (30, lambda p, a, b: call("ne", a, b)),
           "<": (35, lambda p, a, b: call("lt", a, b)), "<=": (35, lambda p, a, b: call("le", a, b)),
           ">": (35, lambda p, a, b: call("gt", a, b)), ">=": (35, lambda p, a, b: call("ge", a, b)),
           "+": (50, _plus), "-": (50, _arithmetic("sub")), "*": (60, _arithmetic("mul")),
           "/": (60, _arithmetic("div")), "%": (60, _arithmetic("mod"))},
    prefix={"!": (70, lambda p, a: call("not", a)), "-": (70, lambda p, a: call("neg", a))},
    functions={
        "ISNULL": _fn("ISNULL", 1, "is_null"), "UPPER": _fn("UPPER", 1, "upper"), "LOWER": _fn("LOWER", 1, "lower"),
        "TRIM": _spaces("^ +| +$"), "LTRIM": _spaces("^ +"), "RTRIM": _spaces(" +$"),
        "LEN": _fn("LEN", 1, "length"), "SUBSTRING": _substring,
        "LEFT": lambda p, a: _count(p, a, "LEFT", "left"), "RIGHT": lambda p, a: _count(p, a, "RIGHT", "right"),
        "ABS": _fn("ABS", 1, "abs"), "CEILING": _fn("CEILING", 1, "ceil"), "FLOOR": _fn("FLOOR", 1, "floor"),
        "POWER": _fn("POWER", 2, "power"), "SQRT": _fn("SQRT", 1, "sqrt"), "YEAR": _fn("YEAR", 1, "year"),
        "MONTH": _fn("MONTH", 1, "month"), "DAY": _fn("DAY", 1, "day"), "REPLACENULL": _fn("REPLACENULL", 2,
                                                                                          "coalesce"),
        "NULL": _null,
        "ROUND": _refused("ROUND", "is not converted: Microsoft's reference does not say how it rounds a half."),
        **{name: _refused(name, "is not converted: its answer depends on the server's clock, region or rules "
                                "this does not know.") for name in ("GETDATE", "GETUTCDATE", "DATEADD", "DATEDIFF",
                                                                    "DATEPART", "REPLACE", "FINDSTRING", "TOKEN",
                                                                    "HEX", "CODEPOINT", "REVERSE", "REPLICATE")},
    },
    constants={"TRUE": TRUE, "FALSE": FALSE},
    bare_columns=False,
    special=_special,
    postfix=_postfix,
)
_OPERATORS = ("==", "!=", "<=", ">=", "&&", "||", "<", ">", "+", "-", "*", "/", "%", "!", "?", ":")


def expression(text: str, columns: dict[str, PWType], what: str) -> Expr:
    if "@[" in text or re.search(r"@\w", text):
        raise NotConverted(f"{what} reads a variable (@[...]), whose value this does not know.")
    if re.search(r"(?<![&|=!<>])[&|^~](?![&|=])", text):
        raise NotConverted(f"{what} uses a bitwise operator, which this does not convert.")
    return ex.parse(text, SSIS, columns, what=what, quotes='"', escape="backslash", brackets=True,
                    operators=_OPERATORS)


# =============================================================== the package


@dataclass
class _Column:
    name: str
    lineage: str
    kind: str
    properties: dict[str, str] = field(default_factory=dict)
    upstream: str | None = None  # an input column's lineage
    usage: str = ""


def _properties(element) -> dict[str, str]:
    found = {}
    for prop in descendants(element, "property") if element is not None else []:
        found[attribute(prop, "name") or ""] = (prop.text or "").strip()
    return found


def _columns(element, tag: str) -> list[_Column]:
    found = []
    for column in descendants(element, tag):
        found.append(_Column(name=attribute(column, "name") or attribute(column, "cachedName") or "",
                             lineage=attribute(column, "lineageId") or attribute(column, "refId") or "",
                             kind=attribute(column, "dataType") or attribute(column, "cachedDataType") or "",
                             properties=_properties(child(column, "properties")),
                             upstream=attribute(column, "lineageId"),
                             usage=attribute(column, "usageType") or ""))
    return found


def convert_ssis(files: dict[str, bytes], lookup) -> Conversion:
    (file_name, data), = files.items()
    root = read_xml(data, file_name)
    if local(root.tag) != "Executable":
        raise NotConverted(f"{file_name} is not an SSIS package (its root is {local(root.tag)}).")
    name = attribute(root, "ObjectName") or posixpath.splitext(posixpath.basename(file_name))[0]
    conversion = Conversion(format="ssis", title=f"the SSIS package {name}")
    managers = {}
    for manager in descendants(root, "ConnectionManager"):
        reference = attribute(manager, "refId") or ""
        inner = child(child(manager, "ObjectData"), "ConnectionManager")
        managers[reference] = (attribute(manager, "ObjectName") or "", attribute(inner, "ConnectionString")
                               if inner is not None else "")
        managers[attribute(manager, "DTSID") or reference] = managers[reference]
    executables = child(root, "Executables")
    recipes_of: dict[str, list[str]] = {}
    overview = conversion.section(f"{file_name}: the package {name}")
    for executable in children(executables, "Executable") if executables is not None else []:
        kind = attribute(executable, "ExecutableType") or ""
        title = attribute(executable, "ObjectName") or "task"
        reference = attribute(executable, "refId") or title
        section = conversion.section(f"{file_name}: {title}")
        if kind in ("Microsoft.Pipeline", "SSIS.Pipeline.3", "SSIS.Pipeline.2") or "Pipeline" in kind:
            made_before = {recipe.key for recipe in conversion.recipes}
            _data_flow(conversion, executable, title, managers, lookup, file_name)
            recipes_of[reference] = [recipe.key for recipe in conversion.recipes if recipe.key not in made_before
                                     and recipe.complete]
            continue
        words = {"Microsoft.ExecuteSQLTask": "It runs SQL against a database, which a workflow here does not do.",
                 "Microsoft.ScriptTask": "It runs a script (C# or Visual Basic), which this does not run.",
                 "Microsoft.SendMailTask": "It sends an email, which a workflow here does not do.",
                 "STOCK:SEQUENCE": "A container of tasks: this converts the data flows at the package's top level.",
                 "STOCK:FORLOOP": "A loop repeats its tasks; a workflow here runs each task once.",
                 "STOCK:FOREACHLOOP": "A loop repeats its tasks; a workflow here runs each task once."}
        section.not_converted(f"task {title}", words.get(kind, f"{kind or 'This task'} is not a task this "
                                                                "converts; Data Flow tasks are."))
    # The workflow: each data flow's recipes (a branch's before what reads it), and the data flows in the order
    # the constraints give.
    from api_gateway.conversions.model import run_in_order

    keys = [key for found in recipes_of.values() for key in found]
    made = run_in_order(conversion, key="workflow:package", name=name,
                        description=f"The SSIS package {name}: its data flows in the order its precedence "
                                    "constraints give.",
                        recipes=[conversion.recipe(key) for key in keys])
    nodes = {reference: [made[1][key] for key in found if key in made[1]] for reference, found in
             recipes_of.items()} if made else {}
    links: list[LinkPlan] = list(made[0].links) if made else []
    constraints = child(root, "PrecedenceConstraints")
    complete = True
    for constraint in children(constraints, "PrecedenceConstraint") if constraints is not None else []:
        source, target = attribute(constraint, "From") or "", attribute(constraint, "To") or ""
        value = attribute(constraint, "Value") or "0"
        operation = attribute(constraint, "EvalOp") or "2"
        if operation not in ("2", "Constraint"):
            overview.not_converted(f"the constraint from {source} to {target}", "It tests an expression, which this "
                                                                                 "does not convert.")
            complete = False
            continue
        if (attribute(constraint, "LogicalAnd") or "True") == "False":
            overview.not_converted(f"the constraint from {source} to {target}", "It lets a task run when any one "
                                                                                 "task before it finishes (OR); a "
                                                                                 "task here waits for all.")
            complete = False
            continue
        condition = {"0": "on_success", "1": "on_failure", "2": "always"}.get(value)
        if source not in nodes or target not in nodes:
            overview.not_converted(f"the constraint from {source.split(chr(92))[-1]} to {target.split(chr(92))[-1]}",
                                   "One of its tasks did not convert, so it links nothing here.")
            complete = False
            continue
        for a in nodes[source]:
            for b in nodes[target]:
                links.append(LinkPlan(a, b, condition or "on_success"))
    if made:
        made[0].links = links
        conversion.workflows.append(made[0])
        overview.converted("the package", f"The workflow “{name}”" + ("" if complete else
                                                                     ", without the parts that did not convert"))
    conversion.notes.append("The package is read, never run: nothing of it ran here.")
    return conversion


def _data_flow(conversion: Conversion, executable, title: str, managers, lookup, file_name: str) -> None:
    pipeline = next(iter(descendants(executable, "pipeline")), None)
    if pipeline is None:
        conversion.section(f"{file_name}: {title}").not_converted(f"task {title}", "Its pipeline is not in the file.")
        return
    flow = Flow(conversion, title, f"ssis:{title}")
    components = descendants(pipeline, "component")
    output_of: dict[str, tuple[str, str]] = {}  # output refId -> (component refId, output name)
    input_of: dict[str, tuple[str, str]] = {}   # input refId -> (component refId, input name)
    for component in components:
        reference = attribute(component, "refId") or attribute(component, "name") or ""
        for output in descendants(component, "output"):
            output_of[attribute(output, "refId") or ""] = (reference, attribute(output, "name") or "")
        for item in descendants(component, "input"):
            input_of[attribute(item, "refId") or ""] = (reference, attribute(item, "name") or "")
    inputs: dict[str, dict[str, tuple[str, str]]] = {}
    for path in descendants(pipeline, "path"):
        start, end = output_of.get(attribute(path, "startId") or ""), input_of.get(attribute(path, "endId") or "")
        if start and end:
            inputs.setdefault(end[0], {})[end[1]] = start
    reader = _Reader(flow, managers, lookup, conversion)
    for component in components:
        reference = attribute(component, "refId") or attribute(component, "name") or ""
        kind = (attribute(component, "componentClassID") or "").split(".")[-1]
        label = f"{_WORDS.get(kind, kind)} {attribute(component, 'name') or ''}".strip()
        section = conversion.section(f"{file_name}: {title}: {label}")
        writes = reader.destination_name(component, kind)
        flow.add(Component(reference, label, inputs.get(reference, {}), reader.build(component, kind, label),
                           section, writes=writes))
    flow.outputs()
    flow.unused()
    for component in flow.components.values():
        if not component.section.entries:
            component.section.converted(component.label, "Its steps are in the recipes of the destinations after it")


_WORDS = {"FlatFileSource": "Flat File Source", "OLEDBSource": "OLE DB Source", "ExcelSource": "Excel Source",
          "DerivedColumn": "Derived Column", "ConditionalSplit": "Conditional Split", "Sort": "Sort",
          "Aggregate": "Aggregate", "MergeJoin": "Merge Join", "UnionAll": "Union All", "Multicast": "Multicast",
          "RowCount": "Row Count", "FlatFileDestination": "Flat File Destination",
          "OLEDBDestination": "OLE DB Destination", "ExcelDestination": "Excel Destination", "Lookup": "Lookup",
          "DataConvert": "Data Conversion", "ScriptComponent": "Script Component"}
_SOURCES = {"FlatFileSource", "OLEDBSource", "ExcelSource"}
_DESTINATIONS = {"FlatFileDestination", "OLEDBDestination", "ExcelDestination"}


class _Reader:
    def __init__(self, flow: Flow, managers, lookup, conversion: Conversion) -> None:
        self.flow = flow
        self.managers = managers
        self.lookup = lookup
        self.conversion = conversion
        #: lineage id -> column name, for every column any component gives
        self.lineage: dict[str, str] = {}

    def file_of(self, component) -> str:
        for connection in descendants(component, "connection"):
            manager = attribute(connection, "connectionManagerID") or attribute(connection, "connectionManagerRefId")
            found = self.managers.get(manager or "")
            if found:
                return found[1] or found[0]
        return ""

    def table_of(self, component) -> str:
        properties = _properties(child(component, "properties"))
        return re.sub(r"[\[\]\"]", "", properties.get("OpenRowset", "")).split(".")[-1]

    def destination_name(self, component, kind: str) -> str | None:
        if kind not in _DESTINATIONS:
            return None
        if kind == "OLEDBDestination":
            return self.table_of(component) or attribute(component, "name")
        path = self.file_of(component).replace("\\", "/")
        return posixpath.splitext(posixpath.basename(path))[0] or attribute(component, "name")

    def build(self, component, kind: str, label: str):
        builders = {"DerivedColumn": self.derived, "ConditionalSplit": self.split, "Sort": self.sort,
                    "Aggregate": self.aggregate, "MergeJoin": self.merge_join, "UnionAll": self.union,
                    "Multicast": self.multicast, "RowCount": self.passthrough}
        if kind in _SOURCES:
            return lambda flow, inputs: self.remember(component, self.source(component, kind, label))
        if kind in _DESTINATIONS:
            return lambda flow, inputs: self.destination(component, inputs, label)
        if kind in builders:
            return lambda flow, inputs: self.remember(component, builders[kind](component, inputs, label))
        reason = {"Lookup": "A Lookup returns one match by its cache's rules, which this does not convert.",
                  "DataConvert": "A Data Conversion changes types by rules (lengths, code pages, regions) this does "
                                 "not convert.",
                  "ScriptComponent": "A Script Component runs code (C# or Visual Basic), which this does not run."}
        return _not(reason.get(kind, f"{kind or 'This component'} is not a component this converts."))

    def remember(self, component, outputs: dict) -> dict:
        """The names of the columns a component gives, by their lineage, for the components after it."""
        for column in _columns(component, "outputColumn"):
            self.lineage[column.lineage] = column.name
            if column.properties.get("SortColumnId"):
                self.lineage.setdefault(column.properties["SortColumnId"], column.name)
        return outputs

    def upstream(self, component, reference: str) -> str:
        """An input column, named by its id or its lineage, as the column it reads."""
        for element in descendants(component, "inputColumn"):
            if reference in (attribute(element, "refId"), attribute(element, "lineageId")):
                return self.lineage.get(attribute(element, "lineageId") or "", attribute(element, "cachedName") or "")
        return self.lineage.get(reference, "")

    def into(self, component, inputs: dict[str, Stream], name: str | None = None) -> Stream:
        if not inputs:
            raise NotConverted("Nothing is connected to its input.")
        return inputs[name] if name else next(iter(inputs.values()))

    # ------------------------------------------------------------ steps

    def source(self, component, kind: str, label: str) -> dict:
        properties = _properties(child(component, "properties"))
        outputs = [o for o in descendants(component, "output") if (attribute(o, "isErrorOut") or "false") != "true"]
        columns = _columns(outputs[0], "outputColumn") if outputs else []
        names = [c.name for c in columns]
        if kind == "OLEDBSource" and properties.get("AccessMode", "0") in ("2", "3"):
            stream = self.command(properties.get("SqlCommand", ""), label)
        else:
            if kind == "FlatFileSource":
                path = self.file_of(component).replace("\\", "/")
                dataset_name, what = posixpath.splitext(posixpath.basename(path))[0], f"the file {posixpath.basename(path)}"
            else:
                dataset_name = self.table_of(component)
                what = f"the table {dataset_name}"
            if not dataset_name:
                raise NotConverted("It reads nothing this can name: no file and no table.")
            need = self.conversion.need(f"source:{dataset_name.lower()}", dataset_name, what, columns=names,
                                        types={c.name: _TYPES.get(c.kind, UNKNOWN) for c in columns})
            found = self.lookup(need)
            if found is None:
                raise NotConverted(f"It reads {what}. Choose the dataset that holds it (none here is called "
                                   f"“{dataset_name}”), then read the package again.")
            stream = Stream(need.key, [], dict(found))
        by_lower = {c.lower(): c for c in stream.columns}
        missing = [n for n in names if n.lower() not in by_lower]
        if missing:
            raise NotConverted(f"What it reads has no column {missing[0]}.")
        stream = select(stream, [by_lower[n.lower()] for n in names], "Keep the source's columns")
        stream = rename(stream, {by_lower[n.lower()]: n for n in names}, "Name them as the source does")
        self.flow.converted(self.flow.labelled(label), f"Reads its columns: {', '.join(names)}")
        return {_output(component): stream}

    def command(self, text: str, label: str) -> Stream:
        from sqlglot import exp

        query = parse(text, f"The SQL command of {label}")
        tables = {}
        defined = {cte.alias.lower() for cte in query.find_all(exp.CTE)}
        for table in query.find_all(exp.Table):
            if table.name.lower() in defined:
                continue
            need = self.conversion.need(f"source:{table.name.lower()}", table.name, f"the table {table.sql()}")
            found = self.lookup(need)
            if found is None:
                raise NotConverted(f"Its SQL reads {table.sql()}. Choose the dataset that holds it, then read the "
                                   "package again.")
            tables[".".join(p for p in (table.catalog, table.db, table.name) if p)] = dataset_table(
                table.name, need.key, found)
            tables[table.name] = tables[".".join(p for p in (table.catalog, table.db, table.name) if p)]
        chain, compiler = compile_model(query, scope=Scope(tables=tables), owner=label, owner_key=f"ssis-sql:{label}",
                                        parameters={})
        self.conversion.recipes.extend(compiler.helpers)
        return Stream(chain.base, chain.steps, chain.columns, chain.lines)

    def passthrough(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        self.flow.converted(self.flow.labelled(label), "Passes the rows on unchanged (it counts them)")
        return {_output(component): stream}

    def multicast(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        self.flow.converted(self.flow.labelled(label), "Gives the same rows to each of its outputs")
        return {attribute(o, "name") or "": stream for o in descendants(component, "output")}

    def derived(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        lines = []
        for column in _columns(component, "inputColumn"):
            if column.usage == "readwrite" and column.properties.get("FriendlyExpression"):
                name = self.lineage.get(column.upstream or "", column.name)
                text = column.properties["FriendlyExpression"]
                stream = derive(stream, name, expression(text, stream.columns, f"The column {name}"),
                                f"Replace {name} with {text}")
                lines.append(f"{name} = {text}")
        for output in descendants(component, "output"):
            if (attribute(output, "isErrorOut") or "false") == "true":
                continue
            for column in _columns(output, "outputColumn"):
                text = column.properties.get("FriendlyExpression") or column.properties.get("Expression", "")
                if not text:
                    continue
                stream = derive(stream, column.name, expression(text, stream.columns, f"The column {column.name}"),
                                f"Add {column.name} = {text}")
                self.lineage[column.lineage] = column.name
                lines.append(f"{column.name} = {text}")
        self.flow.converted(self.flow.labelled(label), [f"Work out {line}" for line in lines] or "Nothing to work out")
        return {_output(component): stream}

    def split(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        outputs = [o for o in descendants(component, "output") if (attribute(o, "isErrorOut") or "false") != "true"]
        conditions, default = [], None
        for output in sorted(outputs, key=lambda o: int(_properties(child(o, "properties")).get("EvaluationOrder",
                                                                                                "0") or 0)):
            properties = _properties(child(output, "properties"))
            if (attribute(output, "isDefaultOut") or properties.get("IsDefaultOut", "false")).lower() == "true":
                default = attribute(output, "name") or "Default"
                continue
            text = properties.get("FriendlyExpression") or properties.get("Expression", "")
            conditions.append((attribute(output, "name") or "", text, expression(text, stream.columns,
                                                                               f"The condition {text!r}")))
        streams, earlier = {}, []
        for name, text, condition in conditions:
            # The first condition that holds takes the row.
            taken = condition if not earlier else call("and", ex.two_valued(condition),
                                                       call("not", _any(earlier)))
            streams[name] = keep_rows(stream, taken, f"Keep the rows where {text}, and no condition before it")
            earlier.append(condition)
        if default:
            streams[default] = keep_rows(stream, call("not", _any(earlier)) if earlier else TRUE,
                                         "Keep the rows no condition took")
        self.flow.converted(self.flow.labelled(label), [f"{name}: {text}" for name, text, _ in conditions] +
                            ([f"{default}: the rest"] if default else []))
        return streams

    def sort(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        properties = _properties(child(component, "properties"))
        if properties.get("EliminateDuplicates", "false").lower() == "true":
            raise NotConverted("It removes duplicate rows, by a rule (which columns are compared) this does not "
                               "convert.")
        keys = []
        for column in _columns(component, "inputColumn"):
            position = int(column.properties.get("NewSortKeyPosition", "0") or 0)
            if position:
                name = self.lineage.get(column.upstream or "", column.name)
                # A negative position sorts descending; NULL sorts first, as SQL Server sorts it.
                keys.append((abs(position), name, position > 0))
        if not keys:
            raise NotConverted("It sorts by nothing.")
        ordered = [(name, ascending, ascending) for _, name, ascending in sorted(keys)]
        self.flow.converted(self.flow.labelled(label), "Sort by " + ", ".join(
            f"{n} {'ascending' if a else 'descending'}" for n, a, _ in ordered))
        for _, name, _ in keys:
            self.sort_keys.setdefault(attribute(component, "refId") or "", []).append(name)
        return {_output(component): sort(stream, ordered, "Sort (Sort)")}

    @property
    def sort_keys(self) -> dict[str, list[str]]:
        if not hasattr(self, "_sort_keys"):
            self._sort_keys = {}
        return self._sort_keys

    def aggregate(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        outputs = [o for o in descendants(component, "output") if (attribute(o, "isErrorOut") or "false") != "true"]
        if len(outputs) != 1:
            raise NotConverted("It has more than one output, which this does not convert.")
        groups, items = [], []
        for column in _columns(outputs[0], "outputColumn"):
            kind = column.properties.get("AggregationType", "")
            source = self.upstream(component, column.properties.get("AggregationColumnId", "")) or column.name
            function = {"0": None, "1": f"COUNT({_q(source)})", "2": "COUNT(*)", "3": f"COUNT(DISTINCT {_q(source)})",
                        "4": f"SUM({_q(source)})", "5": f"AVG({_q(source)})", "6": f"MIN({_q(source)})",
                        "7": f"MAX({_q(source)})"}
            if kind not in function:
                raise NotConverted(f"Its column {column.name} has the aggregation type {kind}, which this does not "
                                   "know.")
            if kind != "2" and source not in stream.columns:
                raise NotConverted(f"Its column {column.name} reads {source}, which the rows coming in do not have.")
            if kind == "0":
                groups.append(source)
                items.append(_q(source) if source == column.name else f"{_q(source)} AS {_q(column.name)}")
            else:
                items.append(f"{function[kind]} AS {_q(column.name)}")
            self.lineage[column.lineage] = column.name
        text = f"SELECT {', '.join(items)} FROM input" + (f" GROUP BY {', '.join(_q(g) for g in groups)}"
                                                           if groups else "")
        self.flow.converted(self.flow.labelled(label), f"Summarise: {', '.join(items)}")
        return {_output(component): sql(stream, text, "Summarise (Aggregate)")}

    def merge_join(self, component, inputs, label) -> dict:
        properties = _properties(child(component, "properties"))
        how = {"2": "inner", "1": "left", "0": "full"}.get(properties.get("JoinType", "2"))
        if how is None:
            raise NotConverted(f"Its join type {properties.get('JoinType')} is not one Microsoft documents.")
        keys = int(properties.get("NumKeyColumns", "1") or 1)
        names = [attribute(i, "name") or "" for i in descendants(component, "input")]
        left_name = next((n for n in names if "Left" in n), names[0] if names else "")
        right_name = next((n for n in names if "Right" in n), names[1] if len(names) > 1 else "")
        if left_name not in inputs or right_name not in inputs:
            raise NotConverted("It needs both its inputs connected.")
        left, right = inputs[left_name], inputs[right_name]
        left_keys = self.keys_of(left)[:keys]
        right_keys = self.keys_of(right)[:keys]
        if len(left_keys) != keys or len(right_keys) != keys:
            raise NotConverted("Its inputs are not sorted on its join keys here (a Sort before each), so its keys "
                               "cannot be told.")
        output = next(o for o in descendants(component, "output"))
        wanted = []
        for column in _columns(output, "outputColumn"):
            source = self.upstream(component, column.properties.get("InputColumnID", "")) or column.name
            wanted.append((column.name, source))
        right_key, right_columns = self.flow.dataset(right, f"{label} right")
        suffix = "__right"
        matching = properties.get("TreatNullsAsEqual", "true").lower() == "true"
        joined = join(left, right_key, right_columns, how=how, on=left_keys, right_on=right_keys,
                      bring=list(right_columns), suffix=suffix, empty_keys="match each other" if matching else
                      "never match", line=f"Join on {', '.join(left_keys)} ({how}{', empty keys matching' if matching else ''})")
        available = list(joined.columns)
        pick = []
        for name, source in wanted:
            found = source if source in available else f"{source}{suffix}" if f"{source}{suffix}" in available else None
            if found is None:
                raise NotConverted(f"Its output column {name} comes from a column this cannot place.")
            pick.append((name, found))
        joined = select(joined, [found for _, found in pick], "Keep its output columns")
        joined = rename(joined, {found: name for name, found in pick}, "Name them as its output does")
        self.flow.converted(self.flow.labelled(label), f"Join ({how}) on {', '.join(left_keys)} = "
                                                       f"{', '.join(right_keys)}")
        return {_output(component): joined}

    def keys_of(self, stream: Stream) -> list[str]:
        """The columns a stream was last sorted by, in order: a Merge Join's keys."""
        for step in reversed(stream.steps):
            if step["step_type"] == "sort_rows":
                return list(step["config"]["columns"])
            if step["step_type"] == "tool" and "ORDER BY" in str(step["config"].get("sql", "")):
                order = step["config"]["sql"].split("ORDER BY", 1)[1]
                return [part.strip().split(" ")[0].strip('"') for part in order.split(",")]
        return []

    def union(self, component, inputs, label) -> dict:
        output = next(o for o in descendants(component, "output"))
        out_columns = _columns(output, "outputColumn")
        lineage_to_output = {c.lineage: c.name for c in out_columns}
        streams = []
        for item in descendants(component, "input"):
            name = attribute(item, "name") or ""
            if name not in inputs:
                continue
            stream = inputs[name]
            mapping = {}
            for column in _columns(item, "inputColumn"):
                target = lineage_to_output.get(column.properties.get("OutputColumnLineageID", ""))
                if target:
                    mapping[self.lineage.get(column.upstream or "", column.name)] = target
            missing = [c.name for c in out_columns if c.name not in mapping.values()]
            if missing:
                raise NotConverted(f"Its input {name} gives nothing for {missing[0]}: SSIS fills that with NULL, "
                                   "which this does not convert.")
            stream = select(stream, list(mapping), f"Keep what input {name} gives")
            stream = rename(stream, mapping, f"Name it as the output does ({name})")
            streams.append(select(stream, [c.name for c in out_columns], "In the output's order"))
        if len(streams) < 2:
            raise NotConverted("It has fewer than two inputs connected.")
        for column in out_columns:
            self.lineage[column.lineage] = column.name
        stream = streams[0]
        for index, other in enumerate(streams[1:], start=2):
            key, _ = self.flow.dataset(other, f"{label} input {index}")
            stream = stream.then({"step_type": "union_datasets", "config": {
                "other_dataset_id": {"$dataset": key}, "deduplicate": False, "column_strategy": "strict"}},
                f"Add the rows of input {index} (Union All)", columns=dict(stream.columns))
        self.flow.converted(self.flow.labelled(label), f"Add the rows of {len(streams)} inputs together")
        return {_output(component): stream}

    def destination(self, component, inputs, label) -> dict:
        stream = self.into(component, inputs)
        external = {attribute(c, "refId") or "": attribute(c, "name") or ""
                    for c in descendants(component, "externalMetadataColumn")}
        mapping, kept = {}, []
        for element in descendants(component, "inputColumn"):
            name = self.lineage.get(attribute(element, "lineageId") or "", attribute(element, "cachedName") or "")
            if name not in stream.columns:
                raise NotConverted(f"It writes {name}, which the rows coming in do not have.")
            kept.append(name)
            mapping[name] = external.get(attribute(element, "externalMetadataColumnId") or "", name) or name
        if kept:
            stream = select(stream, kept, "Keep the columns it writes")
            stream = rename(stream, mapping, "Name them as it writes them")
        return {"Output": stream}


def _output(component) -> str:
    outputs = [o for o in descendants(component, "output") if (attribute(o, "isErrorOut") or "false") != "true"]
    return attribute(outputs[0], "name") or "Output" if outputs else "Output"


def _any(conditions: list[Expr]) -> Expr:
    found = ex.two_valued(conditions[0])
    for condition in conditions[1:]:
        found = call("or", found, ex.two_valued(condition))
    return found


def _not(reason: str):
    def build(flow: Flow, inputs) -> dict:
        raise NotConverted(reason)

    return build


def _q(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'

