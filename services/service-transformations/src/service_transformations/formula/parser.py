"""Parse a formula into an IR expression.

Producing IR directly, rather than a private AST, is the point: a formula then
gets everything the IR already has -- type inference, lineage, and pushdown. A
supported formula becomes SQL and runs at the source instead of pulling the
column across the network.

Precedence follows spreadsheet convention, which is not Python's: ``&`` is text
concatenation and binds tighter than comparison, ``^`` is exponentiation and is
right-associative, and ``=`` means equality.
"""

from __future__ import annotations

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING, PWType

from service_transformations.formula.lexer import Kind, Token, tokenise
from service_transformations.ir.expressions import (
    FUNCTIONS,
    Call,
    Case,
    Column,
    Expr,
    Literal,
)

#: Binding power per binary operator. Higher binds tighter.
_PRECEDENCE = {
    "^": 60,
    "*": 50, "/": 50, "%": 50,
    "+": 40, "-": 40,
    "&": 30,
    "=": 20, "==": 20, "<>": 20, "!=": 20, "<": 20, "<=": 20, ">": 20, ">=": 20,
}

_RIGHT_ASSOCIATIVE = {"^"}

#: Operator -> IR function.
_BINARY = {
    "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "^": "power",
    "&": "concat",
    "=": "eq", "==": "eq", "<>": "ne", "!=": "ne",
    "<": "lt", "<=": "le", ">": "gt", ">=": "ge",
}

#: Spreadsheet names people already know, mapped onto the catalogue.
_ALIASES = {
    "isblank": "is_null",
    "isnull": "is_null",
    "notblank": "is_not_null",
    "len": "length",
    "mid": "substring",
    "find": "position",
    "search": "position",
    "proper": "initcap",
    "sub": "substring",
    "iferror": "if_error",
    "value": "to_number",
    "text": "to_text",
    "isnumber": "is_number",
    "istext": "is_text",
    "weekday": "day_of_week",
    "datediff": "days_between",
    "dateadd": "add_days",
    "regexmatch": "regex_match",
    "regexextract": "regex_extract",
    "regexreplace": "regex_replace",
    "min": "least",     # scalar MIN across arguments, not the aggregate
    "max": "greatest",
}

#: Constants people type as bare names.
_CONSTANTS: dict[str, tuple[object, PWType]] = {
    "true": (True, BOOLEAN),
    "false": (False, BOOLEAN),
    "null": (None, STRING),
    "blank": (None, STRING),
}


class FormulaError(BadRequestError):
    """A formula that cannot be parsed, phrased for the person who wrote it."""


def parse_formula(source: str, *, columns: list[str] | None = None) -> Expr:
    """Parse a formula. ``columns`` enables a helpful message for a typo."""
    tokens = tokenise(source)
    parser = _Parser(tokens, source, columns or [])
    expression = parser.parse_expression(0)
    parser.expect_end()
    return expression


class _Parser:
    def __init__(self, tokens: list[Token], source: str, columns: list[str]) -> None:
        self.tokens = tokens
        self.source = source
        self.columns = columns
        self.index = 0

    # -- plumbing ---------------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def expect(self, kind: Kind, what: str) -> Token:
        if self.current.kind is not kind:
            raise FormulaError(
                f"Expected {what} at position {self.current.position + 1}, "
                f"but found {self._describe(self.current)}."
            )
        return self.advance()

    def expect_end(self) -> None:
        if self.current.kind is not Kind.END:
            raise FormulaError(
                f"Unexpected {self._describe(self.current)} at position "
                f"{self.current.position + 1}. Is an operator missing?"
            )

    @staticmethod
    def _describe(token: Token) -> str:
        if token.kind is Kind.END:
            return "the end of the formula"
        return f"{token.text!r}"

    # -- grammar ----------------------------------------------------------

    def parse_expression(self, minimum: int) -> Expr:
        left = self.parse_unary()
        while True:
            token = self.current
            if token.kind is not Kind.OPERATOR:
                break
            power = _PRECEDENCE.get(token.text)
            if power is None or power < minimum:
                break
            self.advance()
            next_minimum = power if token.text in _RIGHT_ASSOCIATIVE else power + 1
            right = self.parse_expression(next_minimum)
            left = Call(_BINARY[token.text], (left, right))
        return left

    def parse_unary(self) -> Expr:
        token = self.current
        if token.kind is Kind.OPERATOR and token.text in ("-", "+"):
            self.advance()
            operand = self.parse_unary()
            return Call("neg", (operand,)) if token.text == "-" else operand
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        token = self.advance()

        if token.kind is Kind.NUMBER:
            if "." in token.text:
                return Literal(float(token.text), FLOAT64)
            return Literal(int(token.text), INT64)

        if token.kind is Kind.STRING:
            return Literal(token.text, STRING)

        if token.kind is Kind.COLUMN:
            self._check_column(token)
            return Column(token.text)

        if token.kind is Kind.LPAREN:
            inner = self.parse_expression(0)
            self.expect(Kind.RPAREN, "a closing bracket")
            return inner

        if token.kind is Kind.NAME:
            lowered = token.text.lower()
            if self.current.kind is Kind.LPAREN:
                return self.parse_call(token)
            if lowered in _CONSTANTS:
                value, type_ = _CONSTANTS[lowered]
                return Literal(value, type_)
            # A bare word is almost always a column somebody forgot to bracket.
            raise FormulaError(
                f"{token.text!r} at position {token.position + 1} is not a "
                "function or a value. If it is a column, write it in square "
                f"brackets: [{token.text}]."
            )

        raise FormulaError(
            f"Unexpected {self._describe(token)} at position {token.position + 1}."
        )

    def parse_call(self, name_token: Token) -> Expr:
        self.expect(Kind.LPAREN, "an opening bracket")
        arguments: list[Expr] = []
        if self.current.kind is not Kind.RPAREN:
            while True:
                arguments.append(self.parse_expression(0))
                if self.current.kind is Kind.COMMA:
                    self.advance()
                    continue
                break
        self.expect(Kind.RPAREN, "a closing bracket")

        lowered = name_token.text.lower()

        # IF is a CASE, not a function: every dialect writes it natively, and
        # the result type is the widening of both branches.
        if lowered == "if":
            if len(arguments) not in (2, 3):
                raise FormulaError(
                    f"IF takes a condition, a value if true, and optionally a "
                    f"value if false. Got {len(arguments)} argument(s)."
                )
            default = arguments[2] if len(arguments) == 3 else None
            return Case(((arguments[0], arguments[1]),), default=default)

        # IFS(cond1, val1, cond2, val2, ...) -- the multi-branch form.
        if lowered == "ifs":
            if len(arguments) < 2 or len(arguments) % 2 != 0:
                raise FormulaError(
                    "IFS takes condition and value in pairs, for example "
                    "IFS([n] > 10, \"big\", [n] > 5, \"medium\")."
                )
            branches = tuple(
                (arguments[i], arguments[i + 1]) for i in range(0, len(arguments), 2)
            )
            return Case(branches)

        resolved = _ALIASES.get(lowered, lowered)
        if resolved not in FUNCTIONS:
            raise FormulaError(
                f"There is no function called {name_token.text!r}. "
                f"{_suggest(lowered)}"
            )

        signature = FUNCTIONS[resolved]
        if not signature.accepts_arity(len(arguments)):
            raise FormulaError(
                f"{name_token.text.upper()} takes {signature.arity_description()}, "
                f"but {len(arguments)} were given."
            )
        return Call(resolved, tuple(arguments))

    def _check_column(self, token: Token) -> None:
        if not self.columns or token.text in self.columns:
            return
        # Case-insensitive near-miss is by far the commonest mistake.
        match = next((c for c in self.columns if c.lower() == token.text.lower()), None)
        if match:
            raise FormulaError(
                f"There is no column called {token.text!r}. Did you mean [{match}]?"
            )
        raise FormulaError(
            f"There is no column called {token.text!r}. "
            f"Available: {', '.join(sorted(self.columns)[:8])}"
            + (" ..." if len(self.columns) > 8 else "")
        )


def _suggest(name: str) -> str:
    """Point at the nearest catalogue entry, which is usually the intent."""
    import difflib

    candidates = sorted(set(FUNCTIONS) | set(_ALIASES) | {"if", "ifs"})
    close = difflib.get_close_matches(name, candidates, n=1, cutoff=0.7)
    if close:
        return f"Did you mean {close[0].upper()}?"
    return f"Available functions include: {', '.join(candidates[:8])}."


def function_names() -> list[str]:
    """Every name a formula may use, for autocomplete."""
    return sorted({*FUNCTIONS, *_ALIASES, "if", "ifs"})
