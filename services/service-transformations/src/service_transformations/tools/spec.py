"""What a tool is.

A *tool* is one named, parameterised transformation an analyst picks from a menu
-- "trim whitespace", "extract year", "pad left". There are hundreds of them and
there will be hundreds more, so they are declared as data rather than written as
modules: a :class:`ToolSpec` carries everything the platform needs to run it,
offer it, describe it, and test it.

Four consequences fall out of that, and they are the whole reason for this
shape:

* **Every tool compiles to IR.** ``build`` returns a node, so a tool gets type
  inference, lineage and pushdown without writing any of the three.
* **Every tool is type-aware.** ``accepts`` says which column types it applies
  to, so the UI can offer date tools on a date column and not on a number --
  from one declaration, not from a list maintained in the front end.
* **Every tool is tested the same way.** The registry is iterable, so one test
  file runs *all* of them against empty, all-null and single-row input. A new
  tool cannot arrive without those cases, because nobody has to remember.
* **Every tool documents itself, and the documentation is executed.**
  ``example`` is run by a test that asserts the stated output, so the reference
  cannot drift from the behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from shared_python.errors import BadRequestError
from shared_python.types import Kind, PWType

from service_transformations.ir.nodes import Node


class Accepts(str, Enum):
    """Which column types a tool is offered on.

    Deliberately coarse. The point is "do not offer `extract-year` on a number",
    not to encode a full type check -- the IR does that properly when the tool
    runs, and a menu that hides a tool the engine would have accepted is more
    annoying than one that shows a tool the engine refuses with a clear message.
    """

    ANY = "any"
    TEXT = "text"
    NUMERIC = "numeric"
    TEMPORAL = "temporal"
    BOOLEAN = "boolean"
    #: Text or anything renderable as text -- most cleaning tools.
    TEXTUAL = "textual"

    def matches(self, type_: PWType) -> bool:
        if self is Accepts.ANY:
            return True
        if not type_.is_known:
            # An unknown type is offered everything. Hiding tools because the
            # profiler could not decide would make an unprofiled column
            # untouchable, which is exactly when people need the tools most.
            return True
        if self is Accepts.TEXT:
            return type_.kind is Kind.STRING
        if self is Accepts.NUMERIC:
            return type_.is_numeric
        if self is Accepts.TEMPORAL:
            return type_.is_temporal
        if self is Accepts.BOOLEAN:
            return type_.kind is Kind.BOOLEAN
        return type_.kind is Kind.STRING or not type_.is_nested


class ParamKind(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    COLUMN = "column"
    COLUMNS = "columns"
    SELECT = "select"
    #: A free list of strings, one per line in the UI.
    LIST = "list"


@dataclass(frozen=True)
class Param:
    """One configurable value, with enough detail to build a form from it."""

    key: str
    label: str
    kind: ParamKind
    required: bool = True
    default: Any = None
    #: For SELECT.
    options: tuple[str, ...] = ()
    help: str = ""
    placeholder: str = ""
    #: Inclusive bounds for NUMBER/INTEGER.
    minimum: float | None = None
    maximum: float | None = None

    def coerce(self, raw: Any) -> Any:
        """Validate one supplied value, or say plainly what is wrong with it."""
        if raw is None or raw == "":
            if self.required and self.default is None:
                raise BadRequestError(f"{self.label} is required.")
            return self.default

        if self.kind in (ParamKind.NUMBER, ParamKind.INTEGER):
            try:
                value = float(raw) if self.kind is ParamKind.NUMBER else int(raw)
            except (TypeError, ValueError):
                raise BadRequestError(f"{self.label} must be a number.") from None
            if self.minimum is not None and value < self.minimum:
                raise BadRequestError(f"{self.label} cannot be less than {self.minimum:g}.")
            if self.maximum is not None and value > self.maximum:
                raise BadRequestError(f"{self.label} cannot be more than {self.maximum:g}.")
            return value

        if self.kind is ParamKind.BOOLEAN:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str) and raw.lower() in {"true", "false"}:
                return raw.lower() == "true"
            raise BadRequestError(f"{self.label} must be true or false.")

        if self.kind is ParamKind.SELECT:
            if raw not in self.options:
                raise BadRequestError(
                    f"{self.label} must be one of: {', '.join(self.options)}."
                )
            return raw

        if self.kind in (ParamKind.COLUMNS, ParamKind.LIST):
            if isinstance(raw, str):
                items = [part.strip() for part in raw.splitlines() if part.strip()]
            elif isinstance(raw, (list, tuple)):
                items = [str(item) for item in raw]
            else:
                raise BadRequestError(f"{self.label} must be a list.")
            if self.required and not items:
                raise BadRequestError(f"{self.label} needs at least one value.")
            return items

        return str(raw)


@dataclass(frozen=True)
class Example:
    """A worked example, shown in the reference and *run* by a test.

    Documentation that is not executed is documentation that is eventually
    wrong. ``rows`` goes in, the tool runs with ``params``, and ``expect`` is
    asserted against the named output column.
    """

    #: Input rows. Keys are column names; `column` below names the one the tool
    #: is applied to.
    rows: tuple[dict[str, Any], ...]
    params: dict[str, Any] = field(default_factory=dict)
    #: Expected values of the output column, in order.
    expect: tuple[Any, ...] = ()
    #: Which column the tool reads. Defaults to the first key in the first row.
    column: str | None = None
    #: Which column to assert on. Defaults to the tool's output column.
    output: str | None = None
    note: str = ""


#: ``(input_node, resolved_params) -> output_node``
BuildFn = Callable[[Node, dict[str, Any]], Node]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    category: str
    summary: str
    build: BuildFn
    example: Example
    params: tuple[Param, ...] = ()
    synonyms: tuple[str, ...] = ()
    accepts: Accepts = Accepts.ANY
    #: True for tools that read a column and write one. False for tools that
    #: reshape the frame (row filters, column reordering), which the UI offers
    #: from a different place and which have no "target column".
    column_scoped: bool = True
    #: Set when a tool cannot be pushed to a source and must run locally.
    local_only: bool = False

    def resolve(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate a supplied config into the parameters ``build`` expects."""
        known = {param.key for param in self.params} | {"column", "into", "tool"}
        unexpected = sorted(set(config) - known)
        if unexpected:
            raise BadRequestError(
                f"{self.title} does not take: {', '.join(unexpected)}. "
                f"Accepted: {', '.join(sorted(known - {'tool'})) or 'nothing'}."
            )
        return {param.key: param.coerce(config.get(param.key)) for param in self.params}
