"""Power Query M to recipes (E2, X3).

Read as Microsoft publishes the M language: a query is ``let`` steps ``in``
a result, and a file holds one query, or a section document of ``shared``
queries. Each query becomes a recipe of its steps; a query that only reads
a source is that dataset, and another query that names it reads it.

Sources: ``Csv.Document(File.Contents(...))``, ``Excel.Workbook`` with a
sheet or table chosen, and ``Sql.Database`` with a table chosen are datasets
the project has, matched by the file's, sheet's or table's name; ``#table``
is data the query carries.

Steps converted: Table.PromoteHeaders (after a CSV), TransformColumnTypes
(where the column is that type already, or text read as a number, date or
logical), SelectRows, AddColumn, TransformColumns, RemoveColumns,
SelectColumns, RenameColumns, ReorderColumns, Sort, Distinct, FirstN, LastN,
Skip, Group, NestedJoin with ExpandTableColumn, Combine, ReplaceValue,
FillDown and Buffer. In ``each``: arithmetic, ``&``, comparisons, and, or,
not, if then else, ``??`` and the Text, Number and Date functions listed in
the help, with M's own rules: two empty values are equal, an empty value
and a value are not, ``Number.Round`` breaks a tie to even (so it converts
only with RoundingMode.AwayFromZero, which a formula here rounds).
"""

from __future__ import annotations

import csv
import io
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import UNKNOWN, timestamp

from service_transformations.formula.printer import if_chain
from service_transformations.ir.expressions import Column, Expr, Literal

from api_gateway.conversions import expressions as ex
from api_gateway.conversions.expressions import call
from api_gateway.conversions.flows import (
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
from api_gateway.conversions.model import Conversion, NotConverted, RecipePlan, Seed

# ===================================================================== M syntax


@dataclass(frozen=True)
class Tok:
    kind: str  # name | quoted | string | number | op | end
    text: str
    at: int


_M_OPERATORS = ("=>", "<=", ">=", "<>", "??", "...", "..", "=", "<", ">", "+", "-", "*", "/", "&", "(", ")", "[",
                "]", "{", "}", ",", ";", "@", "?", "!")


def tokens_of(text: str) -> list[Tok]:
    found: list[Tok] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char.isspace() or char == "﻿":
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == '"' or text.startswith('#"', index):
            start = index + (2 if char == "#" else 1)
            end, buffer = start, []
            while end < length:
                if text[end] == '"':
                    if end + 1 < length and text[end + 1] == '"':
                        buffer.append('"')
                        end += 2
                        continue
                    break
                if text.startswith("#(", end):  # #(cr), #(lf), #(tab)
                    close = text.find(")", end)
                    escape = text[end + 2:close].lower() if close != -1 else ""
                    buffer.append({"cr": "\r", "lf": "\n", "tab": "\t", "cr,lf": "\r\n"}.get(escape, ""))
                    end = close + 1
                    continue
                buffer.append(text[end])
                end += 1
            if end >= length:
                raise NotConverted(f"A text opened at {index + 1} is never closed.")
            found.append(Tok("quoted" if char == "#" else "string", "".join(buffer), index))
            index = end + 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            end = index
            while end < length and (text[end].isalnum() or text[end] in "._"):
                if text[end] in "eE" and end + 1 < length and text[end + 1] in "+-":
                    end += 1
                end += 1
            found.append(Tok("number", text[index:end], index))
            index = end
            continue
        if char.isalpha() or char in "_#":
            end = index + 1
            while end < length and (text[end].isalnum() or text[end] in "_."):
                end += 1
            found.append(Tok("name", text[index:end].rstrip("."), index))
            index = end if not text[index:end].endswith(".") else end - 1
            continue
        matched = next((op for op in _M_OPERATORS if text.startswith(op, index)), None)
        if matched is None:
            raise NotConverted(f"The query has {char!r} at {index + 1}, which this does not read.")
        found.append(Tok("op", matched, index))
        index += len(matched)
    found.append(Tok("end", "", length))
    return found


@dataclass
class Node:
    kind: str  # name lit list record call each field let if binary unary type item lambda
    value: Any = None
    items: list[Any] = field(default_factory=list)
    at: int = 0


class MParser:
    """M's grammar, as far as queries of steps need it."""

    def __init__(self, text: str) -> None:
        self.tokens = tokens_of(text)
        self.index = 0

    @property
    def current(self) -> Tok:
        return self.tokens[self.index]

    def advance(self) -> Tok:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def is_op(self, text: str) -> bool:
        return self.current.kind == "op" and self.current.text == text

    def is_word(self, text: str) -> bool:
        return self.current.kind == "name" and self.current.text == text

    def expect_op(self, text: str) -> Tok:
        if not self.is_op(text):
            raise NotConverted(f"The query has {self.current.text or 'its end'!r} at {self.current.at + 1} where "
                               f"{text!r} belongs.")
        return self.advance()

    def expect_word(self, text: str) -> Tok:
        if not self.is_word(text):
            raise NotConverted(f"The query has {self.current.text or 'its end'!r} at {self.current.at + 1} where "
                               f"{text!r} belongs.")
        return self.advance()

    def identifier(self) -> str:
        token = self.advance()
        if token.kind not in ("name", "quoted"):
            raise NotConverted(f"The query has {token.text!r} at {token.at + 1} where a name belongs.")
        return token.text

    # -------------------------------------------------------- documents

    def document(self) -> list[tuple[str, Node]]:
        if self.is_word("section"):
            self.advance()
            self.identifier()
            self.expect_op(";")
            queries = []
            while self.current.kind != "end":
                if self.is_op("["):  # an attribute record
                    self.record()
                if self.is_word("shared"):
                    self.advance()
                name = self.identifier()
                self.expect_op("=")
                queries.append((name, self.expression()))
                self.expect_op(";")
            return queries
        query = self.expression()
        if self.is_op(";"):
            self.advance()
        if self.current.kind != "end":
            raise NotConverted(f"The query goes on after its end, at {self.current.at + 1}.")
        return [("", query)]

    # ------------------------------------------------------ expressions

    def expression(self) -> Node:
        if self.is_word("let"):
            start = self.advance().at
            steps = []
            while True:
                name = self.identifier()
                self.expect_op("=")
                steps.append((name, self.expression()))
                if self.is_op(","):
                    self.advance()
                    continue
                break
            self.expect_word("in")
            return Node("let", steps, [self.expression()], start)
        if self.is_word("each"):
            start = self.advance().at
            return Node("each", self.expression(), at=start)
        if self.is_word("if"):
            start = self.advance().at
            condition = self.expression()
            self.expect_word("then")
            yes = self.expression()
            self.expect_word("else")
            return Node("if", None, [condition, yes, self.expression()], start)
        if self.is_op("(") and self._lambda_ahead():
            start = self.current.at
            self.advance()
            names = []
            while not self.is_op(")"):
                names.append(self.identifier())
                if self.is_word("as"):
                    self.advance()
                    self.identifier()
                if self.is_op(","):
                    self.advance()
            self.expect_op(")")
            if self.is_word("as"):
                self.advance()
                self.identifier()
            self.expect_op("=>")
            return Node("lambda", names, [self.expression()], start)
        return self.binary(0)

    def _lambda_ahead(self) -> bool:
        depth, index = 0, self.index
        while index < len(self.tokens):
            token = self.tokens[index]
            if token.kind == "op" and token.text == "(":
                depth += 1
            elif token.kind == "op" and token.text == ")":
                depth -= 1
                if depth == 0:
                    following = self.tokens[index + 1] if index + 1 < len(self.tokens) else None
                    if following is not None and following.kind == "name" and following.text == "as":
                        following = self.tokens[index + 3] if index + 3 < len(self.tokens) else None
                    return following is not None and following.kind == "op" and following.text == "=>"
            index += 1
        return False

    #: Binding power, from M's specification, loosest first.
    _POWER = {"??": 5, "or": 10, "and": 20, "as": 25, "is": 25, "=": 30, "<>": 30, "<": 40, ">": 40, "<=": 40,
              ">=": 40, "&": 50, "+": 60, "-": 60, "*": 70, "/": 70}

    def binary(self, minimum: int) -> Node:
        left = self.unary()
        while True:
            token = self.current
            key = token.text if token.kind in ("op", "name") else None
            power = self._POWER.get(key or "")
            if power is None or power < minimum:
                return left
            self.advance()
            if key in ("as", "is"):
                left = Node("binary", key, [left, Node("type", self._type_name())], token.at)
                continue
            right = self.binary(power + 1)
            left = Node("binary", key, [left, right], token.at)

    def unary(self) -> Node:
        if self.is_op("-") or self.is_op("+") or self.is_word("not"):
            token = self.advance()
            return Node("unary", token.text, [self.unary()], token.at)
        return self.postfix(self.primary())

    def postfix(self, node: Node) -> Node:
        while True:
            if self.is_op("("):
                start = self.advance().at
                args = []
                while not self.is_op(")"):
                    args.append(self.expression())
                    if self.is_op(","):
                        self.advance()
                self.expect_op(")")
                node = Node("call", node, args, start)
            elif self.is_op("{"):
                start = self.advance().at
                key = self.expression()
                self.expect_op("}")
                node = Node("item", node, [key], start)
            elif self.is_op("[") and node.kind in ("name", "call", "item", "field"):
                start = self.advance().at
                name = self.identifier()
                self.expect_op("]")
                node = Node("field", name, [node], start)
            elif self.is_op("?") and node.kind in ("item", "field"):
                self.advance()
            else:
                return node

    def primary(self) -> Node:
        token = self.current
        if token.kind == "string":
            self.advance()
            return Node("lit", token.text, at=token.at)
        if token.kind == "number":
            self.advance()
            text = token.text.replace("_", "")
            if text.lower().startswith("0x"):
                return Node("lit", int(text, 16), at=token.at)
            return Node("lit", float(text) if any(c in text for c in ".eE") else int(text), at=token.at)
        if token.kind == "name" and token.text in ("null", "true", "false"):
            self.advance()
            return Node("lit", {"null": None, "true": True, "false": False}[token.text], at=token.at)
        if token.kind == "name" and token.text == "type":
            self.advance()
            return Node("type", self._type_name(), at=token.at)
        if token.kind in ("name", "quoted"):
            self.advance()
            return Node("name", token.text, at=token.at)
        if self.is_op("["):
            start = self.advance().at
            if self.current.kind in ("name", "quoted") and self.tokens[self.index + 1].kind == "op" and \
                    self.tokens[self.index + 1].text == "]":
                name = self.identifier()
                self.expect_op("]")
                return Node("field", name, [], start)  # [column] of the row, in an each
            entries = []
            while not self.is_op("]"):
                name = self.identifier()
                self.expect_op("=")
                entries.append((name, self.expression()))
                if self.is_op(","):
                    self.advance()
            self.expect_op("]")
            return Node("record", entries, at=start)
        if self.is_op("{"):
            start = self.advance().at
            items = []
            while not self.is_op("}"):
                items.append(self.expression())
                if self.is_op(","):
                    self.advance()
            self.expect_op("}")
            return Node("list", None, items, start)
        if self.is_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        raise NotConverted(f"The query has {token.text or 'its end'!r} at {token.at + 1}, which this does not read.")

    def _type_name(self) -> str:
        if self.is_word("nullable"):
            self.advance()
        if self.is_op("{") or self.is_op("["):  # a list or record type: kept as text of no use here
            depth = 0
            while True:
                token = self.advance()
                if token.kind == "op" and token.text in "{[":
                    depth += 1
                if token.kind == "op" and token.text in "}]":
                    depth -= 1
                    if depth == 0:
                        return "structured"
        return self.identifier()

    def record(self) -> Node:
        """A record written in: a section's attributes."""
        return self.primary()


# ================================================================ values


def _literal(node: Node, what: str) -> Any:
    """A value written in the query: text, a number, a list, a record."""
    if node.kind == "lit":
        return node.value
    if node.kind == "unary" and node.value == "-":
        value = _literal(node.items[0], what)
        if isinstance(value, (int, float)):
            return -value
    if node.kind == "list":
        return [_literal(item, what) for item in node.items]
    if node.kind == "record":
        return {name: _literal(value, what) for name, value in node.value}
    if node.kind == "name" and "." in node.value:
        return node.value  # Order.Descending, JoinKind.LeftOuter, Int64.Type
    if node.kind == "type":
        return f"type {node.value}"
    raise NotConverted(f"{what} is worked out by code, where this converts a value written in.")


def _names(node: Node, what: str) -> list[str]:
    value = _literal(node, what)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise NotConverted(f"{what} is not a list of column names.")


def _pairs(node: Node, what: str) -> list[list[Any]]:
    value = _literal(node, what)
    if isinstance(value, list) and value and not isinstance(value[0], list):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, list) for v in value):
        raise NotConverted(f"{what} is not a list of pairs.")
    return value


_TYPES = {"type text": STRING, "type number": FLOAT64, "type logical": BOOLEAN, "type date": DATE,
          "type datetime": timestamp(), "Int64.Type": INT64, "Int32.Type": INT64, "Int16.Type": INT64,
          "Int8.Type": INT64, "Number.Type": FLOAT64, "Decimal.Type": FLOAT64, "Currency.Type": FLOAT64,
          "Percentage.Type": FLOAT64, "Text.Type": STRING, "Logical.Type": BOOLEAN, "Date.Type": DATE,
          "DateTime.Type": timestamp(), "type any": UNKNOWN, "Any.Type": UNKNOWN}


def _family(kind: PWType) -> str:
    value = kind.kind.value
    if value.startswith(("int", "uint")):
        return "whole"
    if value.startswith(("float", "decimal")):
        return "number"
    return value


# ============================================================ each, as IR


_M_FUNCTIONS = {
    "Text.Upper", "Text.Lower", "Text.Trim", "Text.TrimStart", "Text.TrimEnd", "Text.Length", "Number.Abs",
    "Number.Sqrt", "Number.RoundDown", "Number.RoundUp", "Date.Year", "Date.Month", "Date.Day", "Text.Start",
    "Text.End", "Text.Middle", "Text.Range", "Text.Contains", "Text.StartsWith", "Text.EndsWith", "Text.Replace",
    "Number.Round", "Value.Is", "Number.From", "Text.From", "Date.From", "Number.FromText", "Date.FromText",
}


class Row:
    """An each expression (or a one-parameter function) over a row's columns, as IR."""

    def __init__(self, columns: dict[str, PWType], what: str, *, value: Expr | None = None) -> None:
        self.columns = columns
        self.what = what
        #: What _ is: the row (None) or one column's value (TransformColumns).
        self.value = value
        self.parser = ex.Parser([], ex.Language("M", {}, {}, {}), columns, what)

    def body(self, node: Node) -> Expr:
        if node.kind == "each":
            return self.expr(node.value)
        if node.kind == "lambda" and len(node.value) == 1:
            self.parameter = node.value[0]
            return self.expr(node.items[0])
        if node.kind == "name" and self.value is not None:
            return self.function(node.value, [self.value], node)
        raise NotConverted(f"{self.what} is not an each expression this converts.")

    parameter = "_"

    def expr(self, node: Node) -> Expr:
        kind = node.kind
        if kind == "lit":
            if isinstance(node.value, str):
                return Literal(node.value, STRING)
            return ex.literal(node.value)
        if kind == "field":
            if node.items and not (node.items[0].kind == "name" and node.items[0].value in ("_", self.parameter)):
                raise NotConverted(f"{self.what} reads a field of something other than the row.")
            return self.parser.column(node.value)
        if kind == "name" and node.value in ("_", self.parameter):
            if self.value is None:
                raise NotConverted(f"{self.what} uses the whole row (_), which a formula here cannot.")
            return self.value
        if kind == "unary":
            inner = self.expr(node.items[0])
            if node.value == "not":
                return call("not", inner)
            return call("neg", inner) if node.value == "-" else inner
        if kind == "binary":
            return self.binary(node)
        if kind == "if":
            condition, yes, no = (self.expr(item) for item in node.items)
            return if_chain([(condition, yes)], no)
        if kind == "call" and node.value.kind == "name":
            name = node.value.value
            if name not in _M_FUNCTIONS:
                raise NotConverted(f"{self.what}: {name} is not an M function this converts.")
            # An option such as RoundingMode.AwayFromZero is read by the function, not as a value.
            args = [self.expr(arg) for arg in node.items if not (arg.kind == "name" and "." in arg.value)]
            return self.function(name, args, node)
        raise NotConverted(f"{self.what} has a part ({kind}) this does not convert.")

    def binary(self, node: Node) -> Expr:
        operator = node.value
        if operator in ("as", "is"):
            raise NotConverted(f"{self.what} uses {operator}, a type test this does not convert.")
        a, b = (self.expr(item) for item in node.items)
        if operator == "and":
            return call("and", a, b)
        if operator == "or":
            return call("or", a, b)
        if operator == "??":
            return call("coalesce", a, b)
        if operator == "&":
            if not (self.parser.is_text(a) and self.parser.is_text(b)):
                raise NotConverted(f"{self.what} uses & on something other than text (a list or a record).")
            return call("concat", a, b)
        if operator in ("=", "<>"):
            # M's equality: two empty values are equal, an empty value and a value are not.
            equal = ex.equal_with_empty(a, b)
            return equal if operator == "=" else call("not", equal)
        if operator in ("<", ">", "<=", ">="):
            return call({"<": "lt", ">": "gt", "<=": "le", ">=": "ge"}[operator], a, b)
        if operator in ("+", "-", "*", "/"):
            if not (self.parser.is_number(a) and self.parser.is_number(b)):
                raise NotConverted(f"{self.what} uses {operator} on something other than numbers (dates or "
                                   "durations), which this does not convert.")
            return call({"+": "add", "-": "sub", "*": "mul", "/": "div"}[operator], a, b)
        raise NotConverted(f"{self.what} uses {operator}, which this does not convert.")

    def function(self, name: str, args: list[Expr], node: Node) -> Expr:
        def count(n: int | tuple[int, ...]) -> None:
            allowed = (n,) if isinstance(n, int) else n
            if len(args) not in allowed:
                raise NotConverted(f"{self.what}: {name} takes {' or '.join(map(str, allowed))} arguments here.")

        simple = {"Text.Upper": "upper", "Text.Lower": "lower", "Text.Trim": "trim", "Text.TrimStart": "ltrim",
                  "Text.TrimEnd": "rtrim", "Text.Length": "length", "Number.Abs": "abs", "Number.Sqrt": "sqrt",
                  "Number.RoundDown": "floor", "Number.RoundUp": "ceil", "Date.Year": "year", "Date.Month": "month",
                  "Date.Day": "day"}
        if name in simple:
            count(1)
            return call(simple[name], args[0])
        if name in ("Text.Start", "Text.End"):
            count(2)
            n = ex.whole_literal(self.parser, args[1], f"{name}'s count")
            return call("left" if name == "Text.Start" else "right", args[0], Literal(n, INT64))
        if name in ("Text.Middle", "Text.Range"):
            count((2, 3))
            start = ex.whole_literal(self.parser, args[1], f"{name}'s start")
            if len(args) == 3:
                return call("substring", args[0], Literal(start + 1, INT64),
                            Literal(ex.whole_literal(self.parser, args[2], f"{name}'s count"), INT64))
            return call("substring", args[0], Literal(start + 1, INT64))
        if name in ("Text.Contains", "Text.StartsWith", "Text.EndsWith"):
            count(2)
            needle = ex.text_literal(self.parser, args[1], f"What {name} looks for")
            ir = {"Text.Contains": "contains", "Text.StartsWith": "starts_with", "Text.EndsWith": "ends_with"}[name]
            return call(ir, args[0], Literal(needle, STRING))
        if name == "Text.Replace":
            count(3)
            return call("replace", args[0], Literal(ex.text_literal(self.parser, args[1], "What Text.Replace finds"),
                                                    STRING),
                        Literal(ex.text_literal(self.parser, args[2], "What Text.Replace puts"), STRING))
        if name == "Number.Round":
            count((1, 2, 3))
            mode = node.items[2] if len(node.items) == 3 else None
            if not (mode is not None and mode.kind == "name" and mode.value == "RoundingMode.AwayFromZero"):
                raise NotConverted(f"{self.what}: Number.Round breaks a tie to even unless told otherwise, where a "
                                   "formula here rounds it away from zero; with RoundingMode.AwayFromZero it "
                                   "converts.")
            digits = ex.whole_literal(self.parser, args[1], "Number.Round's digits") if len(args) > 1 else 0
            return call("round", args[0], Literal(digits, INT64))
        if name == "Value.Is" or name.startswith(("Number.From", "Text.From", "Date.From")):
            raise NotConverted(f"{self.what}: {name} reads values by the computer's region settings, which this "
                               "does not know.")
        raise NotConverted(f"{self.what}: {name} is not an M function this converts.")


# ========================================================== the queries


@dataclass
class _Query:
    name: str
    steps: list[tuple[str, Node]]
    result: Node


def convert_power_query(files: dict[str, bytes], lookup) -> Conversion:
    (file_name, data), = files.items()
    text = data.decode("utf-8-sig", errors="replace")
    stem = posixpath.splitext(posixpath.basename(file_name))[0]
    parsed = MParser(text).document()
    conversion = Conversion(format="power_query", title=f"the Power Query {stem}")
    queries = []
    for name, node in parsed:
        name = name or stem
        if node.kind == "let":
            queries.append(_Query(name, node.value, node.items[0]))
        else:
            queries.append(_Query(name, [(name, node)], Node("name", name)))
    reader = _Reader(conversion, lookup, {query.name for query in queries}, file_name)
    for query in _in_order(queries):
        reader.query(query)
    _run_all(conversion)
    conversion.notes.append("The queries are read, never run: nothing of them ran here.")
    return conversion


def _in_order(queries: list[_Query]) -> list[_Query]:
    """Queries after the queries they name."""
    by_name = {query.name: query for query in queries}
    order, seen = [], set()

    def names_in(node: Any) -> set[str]:
        found = set()
        if isinstance(node, Node):
            if node.kind == "name" and node.value in by_name:
                found.add(node.value)
            for item in node.items:
                found |= names_in(item)
            if isinstance(node.value, Node):
                found |= names_in(node.value)
            if isinstance(node.value, list):
                for entry in node.value:
                    if isinstance(entry, tuple):
                        found |= names_in(entry[1])
        return found

    def visit(query: _Query, trail: set[str]) -> None:
        if query.name in seen or query.name in trail:
            return
        for step_name, node in query.steps:
            for other in names_in(node) - {query.name}:
                if other not in {s for s, _ in query.steps}:
                    visit(by_name[other], trail | {query.name})
        seen.add(query.name)
        order.append(query)

    for query in queries:
        visit(query, set())
    return order


class _Reader:
    def __init__(self, conversion: Conversion, lookup, query_names: set[str], file_name: str) -> None:
        self.conversion = conversion
        self.lookup = lookup
        self.query_names = query_names
        self.file_name = file_name
        #: query name -> its stream (a dataset and steps), once converted
        self.done: dict[str, Stream] = {}
        self.failed: dict[str, str] = {}

    def query(self, query: _Query) -> None:
        section = self.conversion.section(f"{self.file_name}: the query {query.name}")
        steps: dict[str, Stream] = {}
        #: Steps that are not tables yet: a source to choose from, a join to expand.
        self.handles: dict[str, Node] = {}
        stream: Stream | None = None
        for step_name, node in query.steps:
            if _is_handle(node):
                self.handles[step_name] = node
                section.nothing_to_do(f"step {step_name}", "It opens a source or joins a table, which the step after "
                                                           "it reads; it is converted there.")
                continue
            try:
                stream = self.step(node, steps, step_name, query.name)
            except NotConverted as exc:
                section.not_converted(f"step {step_name}", exc.reason)
                self.failed[query.name] = f"Its step {step_name} did not convert."
                if stream is not None and stream.steps:
                    self.conversion.recipes.append(RecipePlan(
                        key=f"query:{query.name}", name=query.name[:160], reads=stream.base, steps=stream.steps,
                        columns=stream.columns, complete=False,
                        description=f"Converted from the query {query.name} as far as its step {step_name}, which "
                                    f"did not convert: {exc.reason}"))
                    section.entries[-1].became.append(f"The recipe “{query.name}”, as a draft, with the "
                                                      f"{len(stream.steps)} steps before it")
                return
            previous = list(steps.values())[-1] if steps else None
            steps[step_name] = stream
            section.converted(f"step {step_name}", self._became(stream, previous) or (
                "Nothing changes here: the columns are those types already" if stream is previous else
                self._reads(stream)))
        result = query.result
        if not (result.kind == "name" and result.value in steps):
            try:
                stream = self.table(result, steps, "The query's result", query.name)
            except NotConverted as exc:
                section.not_converted("its result", exc.reason)
                self.failed[query.name] = "Its result did not convert."
                return
        assert stream is not None
        if result.kind == "name" and result.value in steps:
            stream = steps[result.value]
        if stream.steps:
            self.conversion.recipes.append(RecipePlan(
                key=f"query:{query.name}", name=query.name[:160], reads=stream.base, steps=stream.steps,
                columns=stream.columns, description=f"Converted from the Power Query {query.name}."))
            section.converted(f"the query {query.name}", [f"The recipe “{query.name}”, step {i}: {line}"
                                                          for i, line in enumerate(stream.lines, start=1)])
            self.done[query.name] = Stream(f"query:{query.name}", [], dict(stream.columns))
        else:
            section.nothing_to_do(f"the query {query.name}", "It reads its source and changes nothing: the queries "
                                                              "that name it read that dataset.")
            self.done[query.name] = stream

    def _reads(self, stream: Stream) -> str:
        """What a step with nothing of its own to do does: read its source."""
        named = {need.key: need.name for need in self.conversion.needs}
        named.update({seed.key: seed.name for seed in self.conversion.seeds})
        named.update({f"query:{r.name}": r.name for r in self.conversion.recipes})
        return f"Reads the dataset “{named.get(stream.base, stream.base)}”"

    def _became(self, stream: Stream, previous: Stream | None) -> list[str]:
        start = len(previous.lines) if previous is not None and previous.base == stream.base and \
            stream.lines[:len(previous.lines)] == previous.lines else 0
        return stream.lines[start:]

    # ------------------------------------------------------------ steps

    def step(self, node: Node, steps: dict[str, Stream], step_name: str, query: str) -> Stream:
        return self.table(node, steps, f"The step {step_name}", query)

    def table(self, node: Node, steps: dict[str, Stream], what: str, query: str) -> Stream:
        """A table expression: a step's name, another query, a source, or Table.* of one."""
        if node.kind == "name":
            if node.value in steps:
                return steps[node.value]
            if node.value in self.done:
                return self.done[node.value]
            if node.value in self.failed:
                raise NotConverted(f"It reads the query {node.value}, which did not convert.")
            raise NotConverted(f"{what} names {node.value}, which is neither a step nor a query here.")
        if node.kind == "item":
            return self.navigation(node, steps, what)
        if node.kind == "field" and node.items and node.items[0].kind == "item":
            if node.value != "Data":
                raise NotConverted(f"{what} takes the {node.value} of a navigation, where this reads [Data].")
            return self.navigation(node.items[0], steps, what)
        if node.kind == "call" and node.value.kind == "name":
            function = node.value.value
            if function == "Table.PromoteHeaders":
                return self.promoted(node, steps, what)
            if function == "#table":
                return self.inline(node, what, query)
            if function in ("Csv.Document", "Excel.Workbook", "Sql.Database", "Sql.Databases"):
                raise NotConverted(f"{what}: a {function} is read with its headers promoted and a table chosen; "
                                   "this converts it in those steps.")
            if function.startswith("Table."):
                return self.transform(function, node, steps, what, query)
            raise NotConverted(f"{what} uses {function}, which this does not convert.")
        raise NotConverted(f"{what} is not a table this converts.")

    def navigation(self, node: Node, steps: dict[str, Stream], what: str) -> Stream:
        """Source{[Item="Sheet1",Kind="Sheet"]}[Data], or {[Schema="dbo",Item="Orders"]}."""
        key = _literal(node.items[0], f"{what}'s choice")
        if not isinstance(key, dict) or not isinstance(key.get("Item") or key.get("Name"), str):
            raise NotConverted(f"{what} chooses a table by position or by code, where this reads it by name.")
        table_name = str(key.get("Item") or key.get("Name"))
        base = node.value
        source = base if base.kind == "call" else self.handles.get(base.value) if base.kind == "name" else None
        if source is None or source.value.kind != "name" or source.value.value not in ("Excel.Workbook",
                                                                                       "Sql.Database"):
            raise NotConverted(f"{what} chooses from something other than a workbook or a database.")
        what_it_is = f"the sheet {table_name}" if source.value.value == "Excel.Workbook" else \
            f"the table {key.get('Schema') + '.' if key.get('Schema') else ''}{table_name}"
        return self.dataset(table_name, what_it_is, what)

    def promoted(self, node: Node, steps: dict[str, Stream], what: str) -> Stream:
        inner = node.items[0] if node.items else None
        if inner is not None and inner.kind == "name" and inner.value in self.handles:
            inner = self.handles[inner.value]
        if inner is None or not (inner.kind == "call" and inner.value.kind == "name" and
                                 inner.value.value == "Csv.Document"):
            raise NotConverted(f"{what} promotes the headers of something other than a CSV file.")
        source = inner.items[0] if inner.items else None
        if not (source is not None and source.kind == "call" and source.value.kind == "name" and
                source.value.value in ("File.Contents", "Web.Contents") and source.items):
            raise NotConverted(f"{what} reads a CSV from something other than a file.")
        path = _literal(source.items[0], f"{what}'s file")
        if not isinstance(path, str):
            raise NotConverted(f"{what}'s file name is worked out by code.")
        options = _literal(inner.items[1], f"{what}'s options") if len(inner.items) > 1 else {}
        if isinstance(options, dict) and options.get("Delimiter", ",") not in (",", None):
            raise NotConverted(f"{what} reads a file split by {options.get('Delimiter')!r}; this matches a "
                               "dataset by name, which reads its own file.")
        name = posixpath.splitext(posixpath.basename(path.replace("\\", "/")))[0]
        return self.dataset(name, f"the file {posixpath.basename(path.replace(chr(92), '/'))}", what)

    def dataset(self, name: str, what_it_is: str, what: str) -> Stream:
        need = self.conversion.need(f"source:{name.lower()}", name, what_it_is)
        columns = self.lookup(need)
        if columns is None:
            raise NotConverted(f"It reads {what_it_is}. Choose the dataset that holds it (none here is called "
                               f"“{name}”), then read the query again.")
        return Stream(need.key, [], dict(columns))

    def inline(self, node: Node, what: str, query: str) -> Stream:
        if len(node.items) != 2:
            raise NotConverted(f"{what}: #table takes its columns and its rows.")
        names = node.items[0]
        if names.kind == "type":
            raise NotConverted(f"{what} gives #table a typed header, which this does not read; a list of names it "
                               "does.")
        columns = _names(names, f"{what}'s columns")
        rows = _literal(node.items[1], f"{what}'s rows")
        if not isinstance(rows, list) or not all(isinstance(row, list) and len(row) == len(columns) for row in rows):
            raise NotConverted(f"{what}'s rows do not fit its columns.")
        if any(value == "" for row in rows for value in row):
            raise NotConverted(f"{what} holds empty text, which a dataset here cannot tell from no value.")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        writer.writerows([["" if v is None else ("true" if v is True else "false" if v is False else v)
                           for v in row] for row in rows])
        key = f"seed:{query}"
        self.conversion.seeds.append(Seed(key=key, name=f"{query} (data)"[:160], what=f"the rows in {query}",
                                          file_name=f"{re.sub(r'[^A-Za-z0-9]+', '_', query).strip('_') or 'data'}"
                                                    ".csv", data=buffer.getvalue().encode()))
        from api_gateway.conversions.dbt import _seed_columns

        typed = _seed_columns(buffer.getvalue().encode())
        stream = Stream(key, [], typed)
        texts = [name for name, value in zip(columns, rows[0] if rows else []) if isinstance(value, str)
                 and typed.get(name) is not None and typed[name].kind is not STRING.kind]
        if texts:
            stream = stream.then({"step_type": "cast_column_types", "config": {"mappings": {n: "string" for n in
                                                                                         texts}}},
                                 f"Keep {', '.join(texts)} as text, as the query writes them")
        return stream

    # ---------------------------------------------------------- Table.*

    def transform(self, function: str, node: Node, steps: dict[str, Stream], what: str, query: str) -> Stream:
        args = node.items
        if function == "Table.Combine":
            tables = args[0].items if args and args[0].kind == "list" else None
            if not tables or len(tables) < 2:
                raise NotConverted(f"{what}: Table.Combine takes a list of tables written in.")
            stream = self.table(tables[0], steps, what, query)
            for index, other in enumerate(tables[1:], start=2):
                key, columns = self.as_dataset(self.table(other, steps, what, query), f"{query} part {index}")
                merged = {**stream.columns, **{n: k for n, k in columns.items() if n not in stream.columns}}
                stream = stream.then({"step_type": "union_datasets", "config": {
                    "other_dataset_id": {"$dataset": key}, "deduplicate": False, "column_strategy": "union"}},
                    f"Add the rows of table {index}, by column name (Table.Combine)", columns=merged)
            return stream
        if not args:
            raise NotConverted(f"{what}: {function} reads no table.")
        if function == "Table.ExpandTableColumn":
            return self.expand(node, steps, what, query)
        stream = self.table(args[0], steps, what, query)
        rest = args[1:]
        columns = stream.columns
        if function == "Table.Buffer":
            return stream
        if function == "Table.TransformColumnTypes":
            return self.types(stream, rest, what)
        if function == "Table.SelectRows":
            condition = Row(columns, f"{what}'s condition").body(rest[0])
            return keep_rows(stream, condition, "Keep the rows where the condition holds (Table.SelectRows)")
        if function == "Table.AddColumn":
            name = _literal(rest[0], f"{what}'s new column")
            if not isinstance(name, str):
                raise NotConverted(f"{what}'s new column's name is worked out by code.")
            if name in columns:
                raise NotConverted(f"{what} adds {name}, which the table has already: M stops on that.")
            value = Row(columns, f"The new column {name}").body(rest[1])
            return derive(stream, name, value, f"Add {name} (Table.AddColumn)")
        if function == "Table.TransformColumns":
            for pair in self.transforms(rest[0], what):
                name, body = pair
                if name not in stream.columns:
                    raise NotConverted(f"{what} changes {name}, which the table does not have.")
                value = Row(stream.columns, f"The change to {name}", value=Column(name)).body(body)
                stream = derive(stream, name, value, f"Change {name} (Table.TransformColumns)")
            return stream
        if function == "Table.RemoveColumns":
            names = _names(rest[0], f"{what}'s columns")
            missing = [n for n in names if n not in columns]
            if missing:
                raise NotConverted(f"{what} removes {missing[0]}, which the table does not have: M stops on that.")
            return stream.then({"step_type": "drop_columns", "config": {"columns": names}},
                               f"Remove {', '.join(names)}")
        if function in ("Table.SelectColumns", "Table.ReorderColumns"):
            names = _names(rest[0], f"{what}'s columns")
            if function == "Table.ReorderColumns":
                if sorted(names) != sorted(n for n in names if n in columns) or len(names) != len(columns):
                    names = names + [n for n in columns if n not in names]
            return select(stream, names, f"Keep {', '.join(names)}, in that order ({function})")
        if function == "Table.RenameColumns":
            pairs = _pairs(rest[0], f"{what}'s new names")
            return rename(stream, {str(old): str(new) for old, new in pairs}, "Rename columns (Table.RenameColumns)")
        if function == "Table.Sort":
            raw = _literal(rest[0], f"{what}'s order")
            raw = [raw] if isinstance(raw, str) else raw
            keys = []
            for item in raw:
                column, order = (item, "Order.Ascending") if isinstance(item, str) else (item[0], item[1])
                ascending = order in ("Order.Ascending", 0)
                # M puts an empty value before every value.
                keys.append((str(column), ascending, ascending))
            return sort(stream, keys, "Sort (Table.Sort)")
        if function == "Table.Distinct":
            subset = _names(rest[0], f"{what}'s columns") if rest else []
            return distinct(stream, subset, "Remove repeated rows (Table.Distinct)")
        if function in ("Table.FirstN", "Table.LastN", "Table.Skip"):
            n = _literal(rest[0], f"{what}'s count") if rest else 1
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                raise NotConverted(f"{what}'s count is a condition or code, where this converts a number.")
            if function == "Table.FirstN":
                return limit(stream, n, f"Keep the first {n} rows")
            tool = "rows.keep_last" if function == "Table.LastN" else "rows.skip"
            return stream.then({"step_type": "tool", "config": {"tool": tool, "count": n}},
                               f"{'Keep the last' if tool == 'rows.keep_last' else 'Skip the first'} {n} rows")
        if function == "Table.Group":
            return self.group(stream, rest, what)
        if function == "Table.NestedJoin":
            raise NotConverted(f"{what}: Table.NestedJoin makes a column of tables; this converts it with the "
                               "Table.ExpandTableColumn after it.")
        if function == "Table.ReplaceValue":
            return self.replace(stream, rest, what)
        if function == "Table.FillDown":
            for name in _names(rest[0], f"{what}'s columns"):
                if name not in stream.columns:
                    raise NotConverted(f"{what} fills {name}, which the table does not have.")
                temp = f"{name}__filled"
                order = list(stream.columns)
                stream = stream.then({"step_type": "tool", "config": {"tool": "null.fill_forward", "column": name,
                                                                      "into": temp}}, f"Fill {name} down")
                stream = stream.then({"step_type": "drop_columns", "config": {"columns": [name]}},
                                     f"Fill {name} down")
                stream = rename(stream, {temp: name}, f"Fill {name} down")
                stream = select(stream, order, f"Fill {name} down")
            return stream
        raise NotConverted(f"{what}: {function} is not a Table function this converts.")

    def as_dataset(self, stream: Stream, name: str) -> tuple[str, dict[str, PWType]]:
        if not stream.steps:
            return stream.base, dict(stream.columns)
        key = f"query-part:{name}"
        if not self.conversion.recipe(key):
            self.conversion.recipes.append(RecipePlan(key=key, name=name[:160], reads=stream.base,
                                                      steps=stream.steps, columns=stream.columns,
                                                      description=f"Part of a query: {name}."))
        return key, dict(stream.columns)

    def transforms(self, node: Node, what: str) -> list[tuple[str, Node]]:
        items = node.items if node.kind == "list" else []
        if items and items[0].kind != "list":
            items = [node]
        found = []
        for item in items:
            if item.kind != "list" or len(item.items) < 2 or item.items[0].kind != "lit":
                raise NotConverted(f"{what}'s changes are not pairs of a column and a function.")
            found.append((str(item.items[0].value), item.items[1]))
        return found

    def types(self, stream: Stream, rest: list[Node], what: str) -> Stream:
        pairs = _pairs(rest[0], f"{what}'s types")
        if len(rest) > 1:
            raise NotConverted(f"{what} reads values by a culture given to it, which this does not do.")
        casts = {}
        for column, kind in pairs:
            column = str(column)
            target = _TYPES.get(str(kind))
            if column not in stream.columns:
                raise NotConverted(f"{what} types {column}, which the table does not have.")
            if target is None:
                raise NotConverted(f"{what} gives {column} the type {kind}, which this does not convert.")
            have = stream.columns[column]
            if target is UNKNOWN or _family(have) == _family(target):
                continue
            if _family(have) == "whole" and _family(target) == "number":
                continue  # a whole number is a number already
            if _family(have) != "string":
                raise NotConverted(f"{what} makes {column} ({have.kind.value}) a {kind}: M rounds and formats such "
                                   "a change by rules this does not convert.")
            if _family(target) == "whole":
                raise NotConverted(f"{what} reads text in {column} as a whole number, which M rounds by its own "
                                   "rules; this does not convert that.")
            casts[column] = {"number": "float64", "boolean": "boolean", "date": "date"}.get(_family(target), "string")
        if not casts:
            return stream
        return stream.then({"step_type": "cast_column_types", "config": {"mappings": casts}},
                           f"Read {', '.join(casts)} as typed (Table.TransformColumnTypes)")

    def group(self, stream: Stream, rest: list[Node], what: str) -> Stream:
        keys = _names(rest[0], f"{what}'s keys")
        if len(rest) > 2:
            raise NotConverted(f"{what} groups by a kind of grouping (GroupKind) or comparer, which this does not "
                               "convert.")
        aggregations = rest[1].items if rest[1].kind == "list" else []
        if aggregations and aggregations[0].kind != "list":
            aggregations = [rest[1]]
        items = [_sql_name(key) for key in keys]
        for aggregation in aggregations:
            if len(aggregation.items) < 2 or aggregation.items[0].kind != "lit":
                raise NotConverted(f"{what}'s summaries are not a name and an each.")
            name = str(aggregation.items[0].value)
            body = aggregation.items[1]
            body = body.value if body.kind == "each" else body
            items.append(f"{self.summary(body, stream.columns, f'The summary {name}')} AS {_sql_name(name)}")
        if not aggregations:
            raise NotConverted(f"{what} summarises nothing.")
        text = f"SELECT {', '.join(items)} FROM input GROUP BY {', '.join(_sql_name(k) for k in keys)}"
        return sql(stream, text, f"Group by {', '.join(keys)} (Table.Group)")

    def summary(self, body: Node, columns: dict[str, PWType], what: str) -> str:
        if body.kind == "call" and body.value.kind == "name":
            function = body.value.value
            if function == "Table.RowCount" and len(body.items) == 1 and body.items[0].kind == "name" and \
                    body.items[0].value == "_":
                return "COUNT(*)"
            column = body.items[0] if len(body.items) == 1 else None
            if column is not None and column.kind == "field" and not column.items:
                if column.value not in columns:
                    raise NotConverted(f"{what} reads {column.value}, which the table does not have.")
                name = _sql_name(column.value)
                found = {"List.Sum": f"SUM({name})", "List.Average": f"AVG({name})", "List.Min": f"MIN({name})",
                         "List.Max": f"MAX({name})", "List.Count": "COUNT(*)",
                         "List.NonNullCount": f"COUNT({name})", "List.Median": f"MEDIAN({name})"}.get(function)
                if found:
                    return found
            raise NotConverted(f"{what} uses {function}, which this does not convert in a group (List.Sum, "
                               "List.Average, List.Min, List.Max, List.Count, List.NonNullCount, List.Median and "
                               "Table.RowCount it does).")
        raise NotConverted(f"{what} is worked out by code this does not convert.")

    def expand(self, node: Node, steps: dict[str, Stream], what: str, query: str) -> Stream:
        args = node.items
        nested = args[0]
        if nested.kind == "name" and nested.value in self.handles:
            nested = self.handles[nested.value]
        if not (nested.kind == "call" and nested.value.kind == "name" and nested.value.value == "Table.NestedJoin"):
            raise NotConverted(f"{what} expands a column made by something other than Table.NestedJoin.")
        join_args = nested.items
        if len(join_args) < 5:
            raise NotConverted(f"{what}: Table.NestedJoin takes two tables, their keys and the new column.")
        left = self.table(join_args[0], steps, what, query)
        on = _names(join_args[1], f"{what}'s keys")
        right_stream = self.table(join_args[2], steps, what, query)
        right_on = _names(join_args[3], f"{what}'s other keys")
        new_column = _literal(join_args[4], f"{what}'s new column")
        kind = join_args[5].value if len(join_args) > 5 and join_args[5].kind == "name" else "JoinKind.LeftOuter"
        how = {"JoinKind.Inner": "inner", "JoinKind.LeftOuter": "left", "JoinKind.RightOuter": "right",
               "JoinKind.FullOuter": "full", "JoinKind.LeftAnti": "anti"}.get(kind)
        if how is None or len(join_args) > 6:
            raise NotConverted(f"{what} joins by {kind}, which this does not convert.")
        if args[1].kind != "lit" or args[1].value != new_column:
            raise NotConverted(f"{what} expands another column than the one the join made.")
        bring = _names(args[2], f"{what}'s columns to bring")
        names = _names(args[3], f"{what}'s new names") if len(args) > 3 else bring
        right_key, right_columns = self.as_dataset(right_stream, f"{query} · {new_column}")
        missing = [n for n in bring if n not in right_columns]
        if missing:
            raise NotConverted(f"{what} brings {missing[0]}, which the other table does not have.")
        suffix = "__power_query"
        # M matches two empty keys: its equality says they are equal.
        joined = join(left, right_key, right_columns, how=how, on=on, right_on=right_on,
                      bring=[] if how == "anti" else bring, suffix=suffix, empty_keys="match each other",
                      line=f"Join with {new_column} on {', '.join(on)} (Table.NestedJoin, {kind.split('.')[-1]})")
        if how != "anti":
            mapping = {(b if b not in left.columns else f"{b}{suffix}"): n for b, n in zip(bring, names)}
            joined = rename(joined, mapping, f"Name the columns brought {', '.join(names)} "
                                             "(Table.ExpandTableColumn)")
        return joined

    def replace(self, stream: Stream, rest: list[Node], what: str) -> Stream:
        if len(rest) != 4:
            raise NotConverted(f"{what}: Table.ReplaceValue takes the old value, the new, the replacer and columns.")
        old, new = _literal(rest[0], f"{what}'s old value"), _literal(rest[1], f"{what}'s new value")
        replacer = rest[2].value if rest[2].kind == "name" else None
        for name in _names(rest[3], f"{what}'s columns"):
            if name not in stream.columns:
                raise NotConverted(f"{what} replaces in {name}, which the table does not have.")
            column = Column(name)
            if replacer == "Replacer.ReplaceValue":
                value = ex.iif(ex.equal_with_empty(column, ex.literal(old) if not isinstance(old, str) else
                                                   Literal(old, STRING)),
                               ex.literal(new) if not isinstance(new, str) else Literal(new, STRING), column)
            elif replacer == "Replacer.ReplaceText":
                if not (isinstance(old, str) and isinstance(new, str)) or not old:
                    raise NotConverted(f"{what} replaces text with something other than text.")
                value = call("replace", column, Literal(old, STRING), Literal(new, STRING))
            else:
                raise NotConverted(f"{what} replaces with {replacer}, which this does not convert.")
            stream = derive(stream, name, value, f"Replace {_m(old)} with {_m(new)} in {name} (Table.ReplaceValue)")
        return stream


def _m(value: Any) -> str:
    """A value as M writes it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    return str(value)


def _sql_name(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'



def _is_handle(node: Node) -> bool:
    """A step that is not a table yet: a source to read or choose from, or a join to expand."""
    return node.kind == "call" and node.value.kind == "name" and node.value.value in (
        "Csv.Document", "Excel.Workbook", "Sql.Database", "Sql.Databases", "File.Contents", "Table.NestedJoin")


def _run_all(conversion: Conversion) -> None:
    """A workflow running every recipe in order, as running the queries makes every output."""
    from api_gateway.conversions.model import run_in_order

    made = run_in_order(conversion, key="workflow:run", name=f"Run {conversion.title.removeprefix('the ')}",
                        description=f"Runs every recipe converted from {conversion.title}, each after the recipes "
                                    "it reads.")
    if made is not None:
        conversion.workflows.append(made[0])
