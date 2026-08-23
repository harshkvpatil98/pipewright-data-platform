"""Turn formula text into tokens.

Spreadsheet syntax, not Python: ``[column name]`` references (which may contain
spaces), ``=`` for equality rather than assignment, ``<>`` for inequality, and
``&`` for text concatenation. A hand-written lexer rather than Python's own,
because none of that is valid Python and pretending otherwise produces error
messages about the wrong language.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared_python.errors import BadRequestError

MAX_FORMULA_LENGTH = 4_000


class Kind(str, Enum):
    NUMBER = "number"
    STRING = "string"
    COLUMN = "column"
    NAME = "name"
    OPERATOR = "operator"
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    END = "end"


@dataclass(frozen=True)
class Token:
    kind: Kind
    text: str
    #: Character offset, so an error can point at the place rather than describe it.
    position: int


#: Longest first: `<=` must be matched before `<`, or `a <= b` lexes as `a < (= b)`.
_OPERATORS = ("<>", "<=", ">=", "!=", "==", "+", "-", "*", "/", "%", "^", "&", "<", ">", "=")


def tokenise(source: str) -> list[Token]:
    if len(source) > MAX_FORMULA_LENGTH:
        raise BadRequestError(
            f"This formula is {len(source)} characters; the limit is {MAX_FORMULA_LENGTH}."
        )

    text = source.strip()
    # A leading "=" is how spreadsheets mark a formula. Accepted and dropped, so
    # a formula pasted straight from Excel works.
    if text.startswith("="):
        text = text[1:]

    tokens: list[Token] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if char.isspace():
            index += 1
            continue

        if char == "[":
            close = text.find("]", index)
            if close == -1:
                raise BadRequestError(
                    f"A column reference opened at position {index + 1} is never closed. "
                    "Column names go inside square brackets, like [order total]."
                )
            name = text[index + 1 : close].strip()
            if not name:
                raise BadRequestError(f"Empty column reference at position {index + 1}.")
            tokens.append(Token(Kind.COLUMN, name, index))
            index = close + 1
            continue

        if char in "\"'":
            quote = char
            end = index + 1
            buffer: list[str] = []
            while end < length:
                if text[end] == quote:
                    # A doubled quote is a literal quote, as in every spreadsheet.
                    if end + 1 < length and text[end + 1] == quote:
                        buffer.append(quote)
                        end += 2
                        continue
                    break
                buffer.append(text[end])
                end += 1
            if end >= length:
                raise BadRequestError(
                    f"A text value opened at position {index + 1} is never closed."
                )
            tokens.append(Token(Kind.STRING, "".join(buffer), index))
            index = end + 1
            continue

        if char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            end = index
            seen_dot = False
            while end < length and (text[end].isdigit() or (text[end] == "." and not seen_dot)):
                if text[end] == ".":
                    seen_dot = True
                end += 1
            tokens.append(Token(Kind.NUMBER, text[index:end], index))
            index = end
            continue

        if char.isalpha() or char == "_":
            end = index
            while end < length and (text[end].isalnum() or text[end] == "_"):
                end += 1
            tokens.append(Token(Kind.NAME, text[index:end], index))
            index = end
            continue

        if char == "(":
            tokens.append(Token(Kind.LPAREN, char, index))
            index += 1
            continue
        if char == ")":
            tokens.append(Token(Kind.RPAREN, char, index))
            index += 1
            continue
        if char == ",":
            tokens.append(Token(Kind.COMMA, char, index))
            index += 1
            continue

        matched = next((op for op in _OPERATORS if text.startswith(op, index)), None)
        if matched is not None:
            tokens.append(Token(Kind.OPERATOR, matched, index))
            index += len(matched)
            continue

        raise BadRequestError(
            f"{char!r} at position {index + 1} is not something a formula can contain."
        )

    tokens.append(Token(Kind.END, "", length))
    return tokens
