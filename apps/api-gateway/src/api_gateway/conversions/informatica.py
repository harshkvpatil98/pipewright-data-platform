"""An Informatica PowerCenter mapping (XML export) to recipes (E2, X3).

Read as PowerCenter exports a folder: ``SOURCE`` and ``TARGET`` definitions
with their fields, and a ``MAPPING`` of ``TRANSFORMATION``s, ``INSTANCE``s
and ``CONNECTOR``s, each connector joining one field of an instance to one
port of another. Every target becomes a recipe of the transformations
before it (``flows.py``); a source is a dataset the project has, matched by
its name, its fields matched without regard to case.

Transformations converted: Source Qualifier (with Select Distinct),
Expression (output and variable ports that do not read an earlier row),
Filter, Aggregator (group-by ports and SUM, COUNT, AVG, MIN, MAX, MEDIAN),
Sorter (with Null Treated Low and Distinct), Joiner (normal, master outer,
detail outer and full outer; it never matches empty keys, as PowerCenter's
does not), Union, Router (each group and the default), and Target.

The transformation language follows PowerCenter's published rules: ``||``
and CONCAT leave out an empty side and are empty when both are, IIF without
a third value gives 0 for a number (and is refused for text, whose empty
string a dataset here cannot tell from no value), LTRIM and RTRIM remove
spaces only. A function whose every answer the reference does not give
exactly (ROUND, TO_CHAR, MOD, date arithmetic) is refused, not guessed.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import UNKNOWN, timestamp

from service_transformations.formula.printer import if_chain
from service_transformations.ir.expressions import Column, Expr, Literal

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
from api_gateway.conversions.model import Conversion, NotConverted
from api_gateway.conversions.xmlfiles import children, read_xml

_TYPES: dict[str, PWType] = {
    "integer": INT64, "small integer": INT64, "bigint": INT64, "decimal": FLOAT64, "double": FLOAT64,
    "real": FLOAT64, "number": FLOAT64, "string": STRING, "nstring": STRING, "text": STRING, "ntext": STRING,
    "varchar": STRING, "varchar2": STRING, "char": STRING, "nchar": STRING, "nvarchar": STRING,
    "date/time": timestamp(), "date": DATE, "boolean": BOOLEAN,
}


# ============================================================ expressions


def _concat(parser: Parser, a: Expr, b: Expr) -> Expr:
    return ex.concat_ignoring_empty(a, b)


def _arithmetic(name: str):
    def build(parser: Parser, a: Expr, b: Expr) -> Expr:
        if not (parser.is_number(a) and parser.is_number(b)):
            raise parser.refuse("arithmetic here is on numbers; dates and text are refused.")
        if name == "mod":
            raise parser.refuse("% gives a remainder whose sign the reference does not give for every value.")
        return call(name, a, b)

    return build


def _iif(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) == 3:
        return ex.iif(args[0], args[1], args[2])
    if len(args) != 2:
        raise parser.refuse("IIF takes a condition and one or two values.")
    if parser.is_number(args[1]):
        return ex.iif(args[0], args[1], Literal(0, INT64))
    if parser.is_text(args[1]):
        raise parser.refuse("IIF without a third value gives empty text, which a dataset here cannot tell from no "
                            "value; give the third value.")
    return ex.iif(args[0], args[1], NULL)


def _decode(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) < 3:
        raise parser.refuse("DECODE takes a value and at least one search and result.")
    value, rest = args[0], args[1:]
    default = rest.pop() if len(rest) % 2 == 1 else None
    branches = []
    for search, result in zip(rest[::2], rest[1::2]):
        if isinstance(search, Literal) and search.value is None:
            raise parser.refuse("DECODE searching for NULL is not converted.")
        branches.append((call("eq", value, search), result))
    return if_chain(branches, default if default is not None else NULL)


def _spaces(side: str):
    pattern = "^ +" if side == "left" else " +$"

    def build(parser: Parser, args: list[Expr]) -> Expr:
        if len(args) != 1:
            raise parser.refuse("LTRIM and RTRIM with a set of characters are not converted.")
        return call("regex_replace", args[0], Literal(pattern, STRING), Literal("", STRING))

    return build


def _substr(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) not in (2, 3):
        raise parser.refuse("SUBSTR takes a text, a start and a length.")
    start = ex.whole_literal(parser, args[1], "SUBSTR's start")
    if start < 0:
        raise parser.refuse("SUBSTR counting from the end is not converted.")
    start = max(start, 1)  # PowerCenter reads 0 as 1
    if len(args) == 3:
        length = ex.whole_literal(parser, args[2], "SUBSTR's length")
        if length <= 0:
            raise parser.refuse("SUBSTR with no length gives NULL; it is not converted.")
        return call("substring", args[0], Literal(start, INT64), Literal(length, INT64))
    return call("substring", args[0], Literal(start, INT64))


def _date_part(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) != 2:
        raise parser.refuse("GET_DATE_PART takes a date and a format.")
    part = ex.text_literal(parser, args[1], "GET_DATE_PART's format").upper()
    name = {"YYYY": "year", "YY": None, "MM": "month", "DD": "day", "HH": "hour", "HH24": "hour", "MI": "minute"}
    if name.get(part) is None:
        raise parser.refuse(f"GET_DATE_PART with {part!r} is not converted.")
    return call(name[part], args[0])


def _fn(name: str, count: int | tuple[int, ...], ir: str):
    allowed = (count,) if isinstance(count, int) else count

    def build(parser: Parser, args: list[Expr]) -> Expr:
        if len(args) not in allowed:
            raise parser.refuse(f"{name} takes {' or '.join(map(str, allowed))} arguments here.")
        return call(ir, *args)

    return build


def _refused(name: str):
    def build(parser: Parser, args: list[Expr]) -> Expr:
        raise parser.refuse(f"{name} is not converted: the transformation language reference does not give its "
                            "answer for every value (a half, a format, a region), and this does not guess.")

    return build


def _concat_fn(parser: Parser, args: list[Expr]) -> Expr:
    if len(args) != 2:
        raise parser.refuse("CONCAT takes two texts.")
    return ex.concat_ignoring_empty(args[0], args[1])


POWERCENTER = Language(
    name="PowerCenter",
    infix={"OR": (10, lambda p, a, b: call("or", a, b)), "AND": (20, lambda p, a, b: call("and", a, b)),
           "=": (30, lambda p, a, b: call("eq", a, b)), "<>": (30, lambda p, a, b: call("ne", a, b)),
           "!=": (30, lambda p, a, b: call("ne", a, b)), "^=": (30, lambda p, a, b: call("ne", a, b)),
           "<": (35, lambda p, a, b: call("lt", a, b)), "<=": (35, lambda p, a, b: call("le", a, b)),
           ">": (35, lambda p, a, b: call("gt", a, b)), ">=": (35, lambda p, a, b: call("ge", a, b)),
           "||": (40, _concat), "+": (50, _arithmetic("add")), "-": (50, _arithmetic("sub")),
           "*": (60, _arithmetic("mul")), "/": (60, _arithmetic("div")), "%": (60, _arithmetic("mod"))},
    prefix={"NOT": (25, lambda p, a: call("not", a)), "-": (70, lambda p, a: call("neg", a))},
    functions={
        "IIF": _iif, "DECODE": _decode, "ISNULL": _fn("ISNULL", 1, "is_null"), "UPPER": _fn("UPPER", 1, "upper"),
        "LOWER": _fn("LOWER", 1, "lower"), "LTRIM": _spaces("left"), "RTRIM": _spaces("right"),
        "LENGTH": _fn("LENGTH", 1, "length"), "SUBSTR": _substr, "CONCAT": _concat_fn,
        "ABS": _fn("ABS", 1, "abs"), "CEIL": _fn("CEIL", 1, "ceil"), "FLOOR": _fn("FLOOR", 1, "floor"),
        "POWER": _fn("POWER", 2, "power"), "SQRT": _fn("SQRT", 1, "sqrt"), "GET_DATE_PART": _date_part,
        **{name: _refused(name) for name in ("ROUND", "TO_CHAR", "TO_INTEGER", "TO_DECIMAL", "TO_FLOAT", "TO_DATE",
                                             "MOD", "INSTR", "REPLACESTR", "REPLACECHR", "ADD_TO_DATE", "DATE_DIFF",
                                             "TRUNC", "INITCAP", "LPAD", "RPAD", "SYSDATE", "REG_EXTRACT",
                                             "REG_MATCH", "REG_REPLACE")},
    },
    constants={"NULL": NULL, "TRUE": TRUE, "FALSE": FALSE},
    bare_columns=True,
)
_OPERATORS = ("||", "<>", "!=", "^=", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "%")


def _without_comments(text: str) -> str:
    """PowerCenter's -- and // comments, outside quotes."""
    out, quoted, index = [], False, 0
    while index < len(text):
        char = text[index]
        if char == "'":
            quoted = not quoted
        if not quoted and (text.startswith("--", index) or text.startswith("//", index)):
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def expression(text: str, columns: dict[str, PWType], what: str) -> Expr:
    if re.search(r"\$\$|:LKP\.|:SP\.|:MCR\.", text, re.I):
        raise NotConverted(f"{what} uses a parameter, a lookup or a stored procedure ($$, :LKP, :SP), which this "
                           "does not convert.")
    return ex.parse(_without_comments(text), POWERCENTER, columns, what=what, quotes="'", escape="double",
                    brackets=False, operators=_OPERATORS)


# ================================================================= the file


@dataclass
class _Instance:
    name: str
    kind: str  # the TRANSFORMATION_TYPE
    definition: object | None
    #: to port -> (from instance, from field)
    links: dict[str, tuple[str, str]] = field(default_factory=dict)


def convert_informatica(files: dict[str, bytes], lookup) -> Conversion:
    (file_name, data), = files.items()
    root = read_xml(data, file_name)
    if root.tag != "POWERMART":
        raise NotConverted(f"{file_name} is not a PowerCenter export (its root is {root.tag}, not POWERMART).")
    mappings = list(root.iter("MAPPING"))
    if not mappings:
        raise NotConverted(f"{file_name} holds no mapping.")
    stem = posixpath.splitext(posixpath.basename(file_name))[0]
    conversion = Conversion(format="informatica", title=f"the PowerCenter mapping{'s' if len(mappings) > 1 else ''} "
                                                        + ", ".join(m.get("NAME", "") for m in mappings))
    sources = {s.get("NAME", ""): s for s in root.iter("SOURCE")}
    targets = {t.get("NAME", ""): t for t in root.iter("TARGET")}
    shared = {t.get("NAME", ""): t for t in root.iter("TRANSFORMATION")}
    for mapping in mappings:
        _mapping(conversion, mapping, sources, targets, shared, lookup, file_name or stem)
    for kind in ("WORKFLOW", "SESSION", "WORKLET"):
        for item in root.iter(kind):
            conversion.section(f"{file_name}: {kind.lower()} {item.get('NAME', '')}").not_converted(
                f"{kind.lower()} {item.get('NAME', '')}", "Sessions and workflows run a mapping with connections and "
                                                          "settings of their own; this converts the mapping.")
    _run_all(conversion)
    conversion.notes.append("The mapping is read, never run: nothing of it ran here.")
    return conversion


def _mapping(conversion: Conversion, mapping, sources, targets, shared, lookup, file_name: str) -> None:
    name = mapping.get("NAME", "mapping")
    local = {t.get("NAME", ""): t for t in children(mapping, "TRANSFORMATION")}
    instances: dict[str, _Instance] = {}
    for instance in children(mapping, "INSTANCE"):
        kind = instance.get("TRANSFORMATION_TYPE", "")
        definition_name = instance.get("TRANSFORMATION_NAME", instance.get("NAME", ""))
        if kind == "Source Definition":
            definition = sources.get(definition_name)
        elif kind == "Target Definition":
            definition = targets.get(definition_name)
        else:
            definition = local.get(definition_name)
            if definition is None:
                definition = shared.get(definition_name)
        instances[instance.get("NAME", "")] = _Instance(instance.get("NAME", ""), kind, definition)
    for connector in children(mapping, "CONNECTOR"):
        to = instances.get(connector.get("TOINSTANCE", ""))
        if to is not None:
            to.links[connector.get("TOFIELD", "")] = (connector.get("FROMINSTANCE", ""), connector.get("FROMFIELD", ""))
    flow = Flow(conversion, name, f"informatica:{name}")
    reader = _Reader(flow, instances, lookup, conversion)
    for instance in instances.values():
        label = f"{instance.kind} {instance.name}"
        section = conversion.section(f"{file_name}: {name}: {label}")
        upstream = sorted({source for source, _ in instance.links.values()})
        inputs = {f"from {source}": (source, "out") for source in upstream}
        build = reader.build(instance, label, section)
        flow.add(Component(instance.name, label, inputs, build, section,
                           writes=instance.name if instance.kind == "Target Definition" else None))
    flow.outputs()
    flow.unused()
    for component in flow.components.values():
        if not component.section.entries:
            component.section.converted(component.label, "Its steps are in the recipes of the targets after it")


class _Reader:
    def __init__(self, flow: Flow, instances: dict[str, _Instance], lookup, conversion: Conversion) -> None:
        self.flow = flow
        self.instances = instances
        self.lookup = lookup
        self.conversion = conversion

    def ports(self, instance: _Instance) -> list:
        return children(instance.definition, "TRANSFORMFIELD") if instance.definition is not None else []

    def attributes(self, instance: _Instance) -> dict[str, str]:
        return {a.get("NAME", ""): a.get("VALUE", "") for a in children(instance.definition, "TABLEATTRIBUTE")} \
            if instance.definition is not None else {}

    def into(self, instance: _Instance, inputs: dict[str, Stream], ports: list[str] | None = None,
             source: str | None = None) -> Stream:
        """The rows coming into an instance, with its input ports' names."""
        links = {to: link for to, link in instance.links.items() if source is None or link[0] == source}
        if not links:
            raise NotConverted("Nothing is connected to it.")
        sources = {link[0] for link in links.values()}
        if len(sources) != 1:
            raise NotConverted(f"Its ports come from {len(sources)} transformations, where it reads one.")
        upstream = inputs[f"from {sources.pop()}"]
        wanted = [to for to in (ports or list(links)) if to in links]
        fields = [links[to][1] for to in wanted]
        if isinstance(upstream, _Grouped):
            # From a Router: the group whose ports it reads.
            groups = {upstream.port_groups.get(f) for f in fields}
            if len(groups) != 1 or None in groups:
                raise NotConverted("It reads ports of more than one of a Router's groups.")
            upstream = upstream[groups.pop()]
        missing = [f for f in fields if f not in upstream.columns]
        if missing:
            raise NotConverted(f"It reads {missing[0]}, which the transformation before it does not give.")
        if len(set(fields)) != len(fields):
            # One field feeding two ports: each port gets its own copy.
            stream = upstream
            for to, from_field in zip(wanted, fields):
                if to != from_field and to not in stream.columns:
                    stream = derive(stream, to, Column(from_field), f"Copy {from_field} to {to}")
            return select(stream, wanted, "Keep the ports it reads")
        stream = select(upstream, fields, "Keep the ports it reads")
        return rename(stream, {f: to for f, to in zip(fields, wanted)}, "Name them as its ports")

    def build(self, instance: _Instance, label: str, section):
        kind = instance.kind
        builders = {"Source Definition": self.source, "Source Qualifier": self.qualifier, "Expression": self.expression,
                    "Filter": self.filter, "Aggregator": self.aggregator, "Sorter": self.sorter, "Joiner": self.joiner,
                    "Union Transformation": self.union, "Union": self.union, "Router": self.router,
                    "Target Definition": self.target}
        if instance.definition is None:
            return _not(f"The definition of {instance.name} is not in the export.")
        if kind in builders:
            return lambda flow, inputs: builders[kind](instance, inputs, label)
        return _not(f"{kind} is not a transformation this converts.")

    # ------------------------------------------------------------ steps

    def source(self, instance: _Instance, inputs, label) -> dict:
        fields = [f.get("NAME", "") for f in children(instance.definition, "SOURCEFIELD")]
        declared = {f.get("NAME", ""): _TYPES.get(f.get("DATATYPE", "").lower(), UNKNOWN)
                    for f in children(instance.definition, "SOURCEFIELD")}
        name = instance.definition.get("NAME", instance.name)
        need = self.conversion.need(f"source:{name.lower()}", name, f"the source {name}", columns=fields,
                                    types=declared)
        columns = self.lookup(need)
        if columns is None:
            raise NotConverted(f"It reads the source {name}. Choose the dataset that holds it (none here is called "
                               f"“{name}”), then read the mapping again.")
        by_lower = {c.lower(): c for c in columns}
        missing = [f for f in fields if f.lower() not in by_lower]
        if missing:
            raise NotConverted(f"The dataset chosen for {name} has no column {missing[0]}.")
        stream = select(Stream(need.key, [], dict(columns)), [by_lower[f.lower()] for f in fields],
                        f"Keep the source's fields, in its order ({name})")
        stream = rename(stream, {by_lower[f.lower()]: f for f in fields}, f"Name them as the source does ({name})")
        self.flow.converted(self.flow.labelled(label), f"Reads the dataset “{name}”")
        return {"out": stream}

    def qualifier(self, instance: _Instance, inputs, label) -> dict:
        attributes = self.attributes(instance)
        for key in ("Sql Query", "User Defined Join", "Source Filter", "Pre SQL", "Post SQL"):
            if attributes.get(key, "").strip():
                raise NotConverted(f"It has a {key}, SQL it runs in the source database, which this does not "
                                   "convert.")
        ports = [p.get("NAME", "") for p in self.ports(instance)]
        stream = self.into(instance, inputs, ports)
        lines = ["Reads its source's fields"]
        if attributes.get("Select Distinct", "NO").upper() == "YES":
            stream = distinct(stream, [], "Remove repeated rows (Select Distinct)")
            lines.append("Removes repeated rows (Select Distinct)")
        self.flow.converted(self.flow.labelled(label), lines)
        return {"out": stream}

    def expression(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        input_ports = [p.get("NAME", "") for p in ports if "INPUT" in p.get("PORTTYPE", "")]
        stream = self.into(instance, inputs, input_ports)
        lines, temps = [], []
        variables = [p.get("NAME", "") for p in ports if "VARIABLE" in p.get("PORTTYPE", "")]
        for index, port in enumerate(ports):
            port_type = port.get("PORTTYPE", "")
            name = port.get("NAME", "")
            text = port.get("EXPRESSION", "")
            if ("OUTPUT" in port_type and "INPUT" not in port_type) or "VARIABLE" in port_type:
                if "VARIABLE" in port_type:
                    later = variables[variables.index(name):]
                    if any(re.search(rf"\b{re.escape(v)}\b", text, re.I) for v in later):
                        raise NotConverted(f"The variable port {name} reads itself or a later variable: its value "
                                           "from the row before, which this does not convert.")
                    temps.append(name)
                value = expression(text, stream.columns, f"The port {name}")
                stream = derive(stream, name, value, f"Work out {name} = {text}")
                lines.append(f"{name} = {text}")
        outputs = [p.get("NAME", "") for p in ports if "OUTPUT" in p.get("PORTTYPE", "")]
        stream = select(stream, outputs, "Keep its output ports")
        self.flow.converted(self.flow.labelled(label), [f"Work out {line}" for line in lines] or "Passes its ports on")
        return {"out": stream}

    def filter(self, instance: _Instance, inputs, label) -> dict:
        stream = self.into(instance, inputs, [p.get("NAME", "") for p in self.ports(instance)])
        text = self.attributes(instance).get("Filter Condition", "TRUE").strip() or "TRUE"
        condition = expression(text, stream.columns, "The filter condition")
        self.flow.converted(self.flow.labelled(label), f"Keep the rows where {text}")
        return {"out": keep_rows(stream, condition, f"Keep the rows where {text}")}

    def aggregator(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        stream = self.into(instance, inputs, [p.get("NAME", "") for p in ports if "INPUT" in p.get("PORTTYPE", "")])
        groups = [p.get("NAME", "") for p in ports if p.get("EXPRESSIONTYPE", "") == "GROUPBY"]
        items = []
        for port in ports:
            name, port_type = port.get("NAME", ""), port.get("PORTTYPE", "")
            if "OUTPUT" not in port_type:
                continue
            if name in groups:
                items.append(_q(name))
                continue
            text = port.get("EXPRESSION", "").strip()
            match = re.fullmatch(r"(SUM|COUNT|AVG|MIN|MAX|MEDIAN)\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)", text, re.I)
            if not match:
                raise NotConverted(f"The port {name} is {text or 'a passed-through port'}, which gives the last row's "
                                   "value or an expression this does not convert; a single SUM, COUNT, AVG, MIN, "
                                   "MAX or MEDIAN of a port it does.")
            function, argument = match.group(1).upper(), match.group(2)
            if argument != "*" and argument not in stream.columns:
                raise NotConverted(f"The port {name} reads {argument}, which comes in to it under no such name.")
            if argument == "*" and function != "COUNT":
                raise NotConverted(f"The port {name} is {text}, which this does not convert.")
            items.append(f"{function}({_q(argument) if argument != '*' else '*'}) AS {_q(name)}")
        text = f"SELECT {', '.join(items)} FROM input"
        if groups:
            text += " GROUP BY " + ", ".join(_q(g) for g in groups)
        self.flow.converted(self.flow.labelled(label), f"Group by {', '.join(groups) or 'nothing'}: "
                                                       f"{', '.join(items)}")
        return {"out": sql(stream, text, f"Group by {', '.join(groups)} ({instance.name})")}

    def sorter(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        stream = self.into(instance, inputs, [p.get("NAME", "") for p in ports])
        low = self.attributes(instance).get("Null Treated Low", "NO").upper() == "YES"
        keys = []
        for port in ports:
            if port.get("ISSORTKEY", "NO").upper() == "YES":
                ascending = port.get("SORTDIRECTION", "ASCENDING").upper() == "ASCENDING"
                # Empty values are the highest unless treated low.
                keys.append((port.get("NAME", ""), ascending, ascending == low))
        if not keys:
            raise NotConverted("It has no sort key.")
        stream = sort(stream, keys, f"Sort ({instance.name})")
        lines = ["Sort by " + ", ".join(f"{k} {'ascending' if a else 'descending'}" for k, a, _ in keys)]
        if self.attributes(instance).get("Distinct", "NO").upper() == "YES":
            stream = distinct(stream, [], "Remove repeated rows (Distinct)")
            lines.append("Remove repeated rows (Distinct)")
        self.flow.converted(self.flow.labelled(label), lines)
        return {"out": stream}

    def joiner(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        master = [p.get("NAME", "") for p in ports if "MASTER" in p.get("PORTTYPE", "")]
        detail = [p.get("NAME", "") for p in ports if "INPUT" in p.get("PORTTYPE", "") and p.get("NAME", "")
                  not in master]
        master_sources = {instance.links[p][0] for p in master if p in instance.links}
        detail_sources = {instance.links[p][0] for p in detail if p in instance.links}
        if len(master_sources) != 1 or len(detail_sources) != 1:
            raise NotConverted("Its master and detail ports do not come from one transformation each.")
        master_stream = self.into(instance, inputs, master, source=next(iter(master_sources)))
        detail_stream = self.into(instance, inputs, detail, source=next(iter(detail_sources)))
        condition = self.attributes(instance).get("Join Condition", "")
        pairs = []
        for part in re.split(r"\s+AND\s+", condition.strip(), flags=re.I):
            match = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*", part)
            if not match:
                raise NotConverted(f"Its join condition {condition!r} is not ports equal to ports.")
            a, b = match.group(1), match.group(2)
            pair = (a, b) if a in master and b in detail else (b, a) if b in master and a in detail else None
            if pair is None:
                raise NotConverted(f"Its join condition pairs {a} and {b}, which are not one master and one detail "
                                   "port.")
            pairs.append(pair)
        kind = self.attributes(instance).get("Join Type", "Normal Join")
        how = {"Normal Join": "inner", "Master Outer Join": "left", "Detail Outer Join": "right",
               "Full Outer Join": "full"}.get(kind)
        if how is None:
            raise NotConverted(f"Its join type {kind} is not converted.")
        master_key, master_columns = self.flow.dataset(master_stream, f"{instance.name} master")
        # PowerCenter's Joiner does not match empty keys, as SQL does not.
        joined = join(detail_stream, master_key, master_columns, how=how, on=[d for _, d in pairs],
                      right_on=[m for m, _ in pairs], bring=master, suffix="__master",
                      line=f"Join the detail with the master on {condition} ({kind}, {instance.name})")
        outputs = [p.get("NAME", "") for p in ports if "OUTPUT" in p.get("PORTTYPE", "")]
        joined = select(joined, outputs, "Keep its output ports")
        self.flow.converted(self.flow.labelled(label), f"Join the detail with the master on {condition} ({kind})")
        return {"out": joined}

    def union(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        outputs = [p.get("NAME", "") for p in ports if "OUTPUT" in p.get("PORTTYPE", "")]
        groups: dict[str, list] = {}
        for port in ports:
            if "INPUT" in port.get("PORTTYPE", ""):
                groups.setdefault(port.get("GROUP", ""), []).append(port)
        if len(groups) < 2:
            raise NotConverted("It has fewer than two input groups.")
        streams = []
        for group, members in groups.items():
            names = [m.get("NAME", "") for m in members]
            sources = {instance.links[n][0] for n in names if n in instance.links}
            if len(sources) != 1 or len(names) != len(outputs):
                raise NotConverted(f"Its group {group} does not come from one transformation with a port for each "
                                   "output.")
            stream = self.into(instance, inputs, names, source=sources.pop())
            streams.append(rename(stream, dict(zip(names, outputs)), f"Name group {group}'s ports as the output's"))
        stream = streams[0]
        for index, other in enumerate(streams[1:], start=2):
            key, _ = self.flow.dataset(other, f"{instance.name} group {index}")
            stream = stream.then({"step_type": "union_datasets", "config": {
                "other_dataset_id": {"$dataset": key}, "deduplicate": False, "column_strategy": "strict"}},
                f"Add the rows of group {index} (Union)", columns=dict(stream.columns))
        self.flow.converted(self.flow.labelled(label), f"Add the rows of {len(streams)} groups together")
        return {"out": stream}

    def router(self, instance: _Instance, inputs, label) -> dict:
        ports = self.ports(instance)
        input_ports = [p.get("NAME", "") for p in ports if "INPUT" in p.get("PORTTYPE", "")]
        stream = self.into(instance, inputs, input_ports)
        groups = [(g.get("NAME", ""), g.get("EXPRESSION", ""), g.get("TYPE", ""))
                  for g in children(instance.definition, "GROUP") if g.get("TYPE", "") != "INPUT"]
        conditions = {}
        for group, text, kind in groups:
            if kind != "OUTPUT/DEFAULT":
                conditions[group] = expression(text, stream.columns, f"The group {group}'s condition")
        streams = {}
        for group, text, kind in groups:
            if kind == "OUTPUT/DEFAULT":
                condition = call("not", ex.literal(False)) if not conditions else call("not", _any(list(
                    conditions.values())))
                line = f"Keep the rows no group took ({group})"
            else:
                condition, line = conditions[group], f"Keep the rows where {text} ({group})"
            grouped = keep_rows(stream, condition, line)
            renamed = {p.get("REF_FIELD", ""): p.get("NAME", "") for p in ports
                       if p.get("GROUP", "") == group and p.get("REF_FIELD")}
            streams[group] = rename(select(grouped, list(renamed), "Keep the group's ports"), renamed,
                                    f"Name them as the group's ports ({group})")
        # A downstream instance reads one group: it is told by the ports it reads.
        self._router_groups[instance.name] = {p.get("NAME", ""): p.get("GROUP", "") for p in ports}
        self.flow.converted(self.flow.labelled(label), [f"Group {g}: {t or 'the rest'}" for g, t, _ in groups])
        return {"out": _Grouped(streams, self._router_groups[instance.name])}

    @property
    def _router_groups(self) -> dict[str, dict[str, str]]:
        if not hasattr(self, "_groups"):
            self._groups = {}
        return self._groups

    def target(self, instance: _Instance, inputs, label) -> dict:
        fields = [f.get("NAME", "") for f in children(instance.definition, "TARGETFIELD")]
        missing = [f for f in fields if f not in instance.links]
        if missing:
            raise NotConverted(f"Nothing writes its field {missing[0]}.")
        return {"out": self.into(instance, inputs, fields)}


class _Grouped(dict):
    """A Router's output: one stream per group, read by the group whose ports are connected."""

    def __init__(self, streams: dict[str, Stream], port_groups: dict[str, str]) -> None:
        super().__init__(streams)
        self.port_groups = port_groups


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


def _run_all(conversion: Conversion) -> None:
    """A workflow running every recipe in order, as running the PowerCenter mapping makes every output."""
    from api_gateway.conversions.model import run_in_order

    made = run_in_order(conversion, key="workflow:run", name=f"Run {conversion.title.removeprefix('the ')}",
                        description=f"Runs every recipe converted from {conversion.title}, each after the recipes "
                                    "it reads.")
    if made is not None:
        conversion.workflows.append(made[0])
