"""Reading another tool's expressions as formulas (E2, X3).

Alteryx, Informatica, SSIS, Talend (Java) and Power Query each write
expressions in their own language. Each language here is a table for one
parser: its operators and how tightly they bind, what a name is (a column,
a constant, a function) and what each function means, written as the
formula functions that mean exactly that, nulls included. The result is an
IR expression, saved as a formula (``formula/printer.py``), so the step
reads like one written by hand.

A function, an operator on a kind of value, or a construct a language has
that is not in its table is refused by name, with the reason: never read as
something close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING, PWType
from shared_python.types.lattice import Kind

from service_transformations.formula.printer import if_chain
from service_transformations.ir.expressions import Call, Column, Expr, Literal

from api_gateway.conversions.model import NotConverted

NULL = Literal(None, STRING)
TRUE = Literal(True, BOOLEAN)
FALSE = Literal(False, BOOLEAN)
_TEXT = {Kind.STRING}
_NUMBER = {Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64, Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64,
           Kind.FLOAT32, Kind.FLOAT64, Kind.DECIMAL}
_WHOLE = {Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64, Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64}


# ------------------------------------------------------------------ tokens


@dataclass(frozen=True)
class Token:
    kind: str  # number | string | column | name | op | ( | ) | , | end
    text: str
    at: int


def tokenise(text: str, *, quotes: str, escape: str = "double", brackets: bool = True,
             operators: tuple[str, ...] = (), name_extra: str = "_", what: str = "The expression") -> list[Token]:
    """Tokens of an expression. ``escape``: "double" (a quote doubled) or "backslash"."""
    tokens: list[Token] = []
    index, length = 0, len(text)
    ordered = sorted(operators, key=len, reverse=True)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char == "/" and text.startswith("//", index) and "//" not in operators:
            end = text.find("\n", index)
            index = length if end == -1 else end
            continue
        if char == "/" and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if brackets and char == "[":
            close = text.find("]", index)
            if close == -1:
                raise NotConverted(f"{what} opens a [ at {index + 1} it never closes.")
            tokens.append(Token("column", text[index + 1:close], index))
            index = close + 1
            continue
        if char in quotes:
            end, buffer = index + 1, []
            while end < length:
                if escape == "backslash" and text[end] == "\\" and end + 1 < length:
                    buffer.append({"n": "\n", "t": "\t", "r": "\r"}.get(text[end + 1], text[end + 1]))
                    end += 2
                    continue
                if text[end] == char:
                    if escape == "double" and end + 1 < length and text[end + 1] == char:
                        buffer.append(char)
                        end += 2
                        continue
                    break
                buffer.append(text[end])
                end += 1
            if end >= length:
                raise NotConverted(f"{what} opens a text at {index + 1} it never closes.")
            tokens.append(Token("string", "".join(buffer), index))
            index = end + 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            end, dot = index, False
            while end < length and (text[end].isdigit() or (text[end] == "." and not dot)):
                dot = dot or text[end] == "."
                end += 1
            if end < length and text[end] in "eE" and end + 1 < length and (
                    text[end + 1].isdigit() or text[end + 1] in "+-"):
                end += 2
                while end < length and text[end].isdigit():
                    end += 1
            while end < length and text[end] in "lLdDfFmM":  # Java and C# number suffixes
                end += 1
            tokens.append(Token("number", text[index:end], index))
            index = end
            continue
        if char.isalpha() or (char in name_extra and char != "."):  # a name never starts with a dot
            end = index
            while end < length and (text[end].isalnum() or text[end] in name_extra):
                end += 1
            tokens.append(Token("name", text[index:end], index))
            index = end
            continue
        if char in "(),":
            tokens.append(Token(char, char, index))
            index += 1
            continue
        matched = next((op for op in ordered if text.startswith(op, index)), None)
        if matched is None:
            raise NotConverted(f"{what} has {char!r} at {index + 1}, which this does not read.")
        tokens.append(Token("op", matched, index))
        index += len(matched)
    tokens.append(Token("end", "", length))
    return tokens


# ------------------------------------------------------------------ parser

Binary = Callable[["Parser", Expr, Expr], Expr]
Unary = Callable[["Parser", Expr], Expr]
Function = Callable[["Parser", list[Expr]], Expr]


@dataclass
class Language:
    name: str
    #: operator or keyword (upper case) -> (binding power, build)
    infix: dict[str, tuple[int, Binary]]
    #: prefix operator or keyword (upper case) -> (binding power, build)
    prefix: dict[str, tuple[int, Unary]]
    #: function name (upper case) -> build
    functions: dict[str, Function]
    #: constant name (upper case) -> value
    constants: dict[str, Expr] = field(default_factory=dict)
    #: Whether a bare name is a column (Informatica, SSIS) rather than an error.
    bare_columns: bool = False
    #: A language's own forms (IF ... THEN ..., a ? b : c, row.column): (parser, token) -> Expr or None.
    special: Callable[["Parser", Token], Expr | None] | None = None
    #: An operator after an expression with forms of its own (?:, method calls).
    postfix: Callable[["Parser", Expr, Token, int], Expr | None] | None = None
    case_sensitive_names: bool = False


class Parser:
    def __init__(self, tokens: list[Token], language: Language, schema: dict[str, PWType], what: str) -> None:
        self.tokens = tokens
        self.language = language
        self.schema = schema
        self.what = what
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def word(self, token: Token | None = None) -> str:
        token = token or self.current
        return token.text if self.language.case_sensitive_names else token.text.upper()

    def at_word(self, *words: str) -> bool:
        return self.current.kind in ("name", "op") and self.word() in words

    def expect(self, kind: str, text: str | None = None) -> Token:
        token = self.current
        if token.kind != kind or (text is not None and self.word(token) != text):
            shown = text or kind
            found = token.text or "the end"
            raise NotConverted(f"{self.what} has {found!r} at {token.at + 1} where {shown!r} belongs.")
        return self.advance()

    def parse(self) -> Expr:
        result = self.expression(0)
        if self.current.kind != "end":
            raise NotConverted(f"{self.what} has {self.current.text!r} at {self.current.at + 1}, which this does "
                               "not read.")
        return result

    def expression(self, minimum: int) -> Expr:
        left = self.unary()
        while True:
            token = self.current
            if token.kind in ("end", ")", ","):
                break
            if self.language.postfix is not None:
                found = self.language.postfix(self, left, token, minimum)
                if found is not None:
                    left = found
                    continue
            key = self.word(token) if token.kind in ("op", "name") else None
            if key is None or key not in self.language.infix:
                break
            power, build = self.language.infix[key]
            if power < minimum:
                break
            self.advance()
            right = self.expression(power + 1)
            left = build(self, left, right)
        return left

    def unary(self) -> Expr:
        token = self.current
        if token.kind in ("op", "name"):
            key = self.word(token)
            if key in self.language.prefix:
                power, build = self.language.prefix[key]
                self.advance()
                return build(self, self.expression(power))
        return self.primary()

    def primary(self) -> Expr:
        token = self.current
        if self.language.special is not None:
            found = self.language.special(self, token)
            if found is not None:
                return found
        token = self.advance()
        if token.kind == "number":
            return number(token.text.rstrip("lLdDfFmM"))
        if token.kind == "string":
            return Literal(token.text, STRING)
        if token.kind == "column":
            return self.column(token.text, token.at)
        if token.kind == "(":
            inner = self.expression(0)
            self.expect(")")
            return inner
        if token.kind == "name":
            key = self.word(token)
            if self.current.kind == "(":
                return self.call(token)
            if key in self.language.constants:
                return self.language.constants[key]
            if self.language.bare_columns:
                return self.column(token.text, token.at)
        raise NotConverted(f"{self.what} has {token.text or 'nothing'!r} at {token.at + 1}, which this does not "
                           "read.")

    def arguments(self) -> list[Expr]:
        self.expect("(")
        found: list[Expr] = []
        if self.current.kind != ")":
            while True:
                found.append(self.expression(0))
                if self.current.kind == ",":
                    self.advance()
                    continue
                break
        self.expect(")")
        return found

    def call(self, name: Token) -> Expr:
        key = self.word(name)
        build = self.language.functions.get(key)
        if build is None:
            raise NotConverted(f"{self.what} uses {name.text}(), which is not a {self.language.name} function this "
                               "converts.")
        return build(self, self.arguments())

    def column(self, name: str, at: int = 0) -> Column:
        if name in self.schema:
            return Column(name)
        matches = [column for column in self.schema if column.lower() == name.lower()]
        if len(matches) == 1:
            return Column(matches[0])
        raise NotConverted(f"{self.what} names {name}, which is not a column here. The columns are "
                           f"{', '.join(self.schema) or 'none'}.")

    # ------------------------------------------------------------ types

    def kind(self, expr: Expr) -> Kind:
        return expr.type_of(self.schema).kind

    def is_text(self, expr: Expr) -> bool:
        return self.kind(expr) in _TEXT or (isinstance(expr, Literal) and isinstance(expr.value, str))

    def is_number(self, expr: Expr) -> bool:
        return self.kind(expr) in _NUMBER

    def is_whole(self, expr: Expr) -> bool:
        return self.kind(expr) in _WHOLE

    def known(self, expr: Expr) -> bool:
        return self.kind(expr) is not Kind.UNKNOWN or (isinstance(expr, Literal) and expr.value is None)

    def refuse(self, reason: str) -> NotConverted:
        return NotConverted(f"{self.what}: {reason}")


def parse(text: str, language: Language, schema: dict[str, PWType], *, what: str, quotes: str = "\"'",
          escape: str = "double", brackets: bool = True, operators: tuple[str, ...] = (),
          name_extra: str = "_") -> Expr:
    """An expression in a language, as an IR expression over these columns."""
    if not text or not text.strip():
        raise NotConverted(f"{what} is empty.")
    tokens = tokenise(text, quotes=quotes, escape=escape, brackets=brackets, operators=operators,
                      name_extra=name_extra, what=what)
    return Parser(tokens, language, schema, what).parse()


# ----------------------------------------------------------------- building


def call(name: str, *args: Expr) -> Call:
    return Call(name, tuple(args))


def number(text: str) -> Expr:
    if any(c in text for c in ".eE"):
        return Literal(float(text), FLOAT64)
    return Literal(int(text), INT64)


def literal(value) -> Expr:
    """A constant as the formula parser reads it back: a negative number is a minus sign before it."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return Literal(value, BOOLEAN)
    if isinstance(value, (int, float)):
        written = Literal(abs(value), INT64 if isinstance(value, int) else FLOAT64)
        return call("neg", written) if value < 0 else written
    return Literal(str(value), STRING)


def iif(condition: Expr, yes: Expr, no: Expr | None) -> Expr:
    return if_chain([(condition, yes)], no)


def whole_literal(parser: Parser, arg: Expr, what: str) -> int:
    """A count or a position, which the formula functions take as a number written in."""
    if isinstance(arg, Literal) and isinstance(arg.value, int) and not isinstance(arg.value, bool):
        return arg.value
    if isinstance(arg, Call) and arg.name == "neg" and isinstance(arg.args[0], Literal) and isinstance(
            arg.args[0].value, int):
        return -arg.args[0].value
    raise parser.refuse(f"{what} is worked out from the row; this converts it as a number written in.")


def text_literal(parser: Parser, arg: Expr, what: str) -> str:
    if isinstance(arg, Literal) and isinstance(arg.value, str):
        return arg.value
    raise parser.refuse(f"{what} is worked out from the row; this converts it as a text written in.")


def never_empty(expr: Expr) -> bool:
    """Whether an expression can never be empty, so guarding it changes nothing."""
    if isinstance(expr, Literal):
        return expr.value is not None
    if isinstance(expr, Call) and expr.name == "concat":
        return all(never_empty(arg) for arg in expr.args)
    if isinstance(expr, Call) and expr.name == "coalesce":
        return never_empty(expr.args[-1])
    return False


def concat_ignoring_empty(a: Expr, b: Expr) -> Expr:
    """Joined text where an empty side is left out, and two empty sides are empty (Alteryx's +,
    Informatica's ||)."""
    def guarded(side: Expr) -> Expr:
        return side if never_empty(side) else call("coalesce", side, Literal("", STRING))

    joined = call("concat", guarded(a), guarded(b))
    if never_empty(a) or never_empty(b):
        return joined  # one side is never empty, so neither is the whole
    return iif(call("and", call("is_null", a), call("is_null", b)), NULL, joined)


def two_valued(comparison: Expr) -> Expr:
    """A comparison that is false, never empty, where a side is empty."""
    return call("coalesce", comparison, FALSE)


def equal_with_empty(a: Expr, b: Expr) -> Expr:
    """Equal, where two empty values are equal and an empty and a value are not (Alteryx's =)."""
    if isinstance(b, Literal) and b.value is None:
        return call("is_null", a)
    if isinstance(a, Literal) and a.value is None:
        return call("is_null", b)
    if isinstance(b, Literal) and b.value is not None:
        return two_valued(call("eq", a, b))
    if isinstance(a, Literal) and a.value is not None:
        return two_valued(call("eq", a, b))
    return call("or", call("and", call("is_null", a), call("is_null", b)), two_valued(call("eq", a, b)))

