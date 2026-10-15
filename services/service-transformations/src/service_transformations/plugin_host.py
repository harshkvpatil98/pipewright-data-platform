"""A plugin's tools and formula functions, made into the library's own (X1).

A plugin tool becomes a `ToolSpec` like any other: a column tool that runs
here, an empty value staying empty without the plugin being asked, its
example run by the library's structural checks (`tools.conformance`). A
plugin function joins the function catalogue with no SQL lowering, so it runs
here and never in a database, and is checked for its examples and for an
empty argument giving an empty answer.

Registering and removing are both here, so a plugin that fails a check after
it is registered leaves nothing behind.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, DATE, FLOAT64, INT64, STRING, timestamp
from shared_python.types.lattice import PWType

from service_transformations.ir.expressions import FUNCTIONS, Call, Literal, Signature
from service_transformations.ir.pandas_backend import _EXTENSIONS, evaluate
from service_transformations.ir.pandas_functions import HANDLERS
from service_transformations.tools import TOOLS, register
from service_transformations.tools.local import column_extension
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

_TYPES: dict[str, PWType] = {"text": STRING, "number": FLOAT64, "integer": INT64, "boolean": BOOLEAN,
                             "date": DATE, "timestamp": timestamp()}
_ACCEPTS = {"any": Accepts.ANY, "text": Accepts.TEXTUAL, "number": Accepts.NUMERIC, "date": Accepts.TEMPORAL,
            "boolean": Accepts.BOOLEAN}
_KINDS = {"text": ParamKind.TEXT, "number": ParamKind.NUMBER, "integer": ParamKind.INTEGER,
          "boolean": ParamKind.BOOLEAN, "select": ParamKind.SELECT}


def _plain(value: Any) -> Any:
    """A value as Python has it, not as pandas or numpy does."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


# -------------------------------------------------------------------- tools


def tool_spec(plugin: str, tool: Any) -> ToolSpec:
    """The library's ToolSpec for an SDK ``Tool``; registering it is `add_tool`'s."""
    name = f"{plugin}.{tool.name}"
    keys = tuple(param.key for param in tool.params)

    def values(series: pd.Series, config: dict[str, Any]) -> list[Any]:
        settings = {key: config.get(key) for key in keys}
        out = []
        for value in series:
            if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                out.append(None)
                continue
            try:
                out.append(tool.transform(_plain(value), settings))
            except Exception as exc:  # noqa: BLE001 - said in the run, naming the plugin
                raise BadRequestError(f"{tool.title} (from the {plugin} plugin) could not change {value!r}: "
                                      f"{exc}") from exc
        return out

    result = None if tool.returns == "same" else _TYPES[tool.returns]
    example = tool.example
    return ToolSpec(
        name=name, title=tool.title, category=tool.category, summary=tool.summary,
        build=column_extension(name, result, values, keys=keys),
        example=Example(rows=tuple({"value": value} for value in example.values), params=dict(example.params),
                        column="value", output="value", expect=tuple(example.expect)),
        params=tuple(Param(param.key, param.label, _KINDS[param.kind], required=param.required,
                           default=param.default, options=tuple(param.options), help=param.help)
                     for param in tool.params),
        synonyms=tuple(tool.synonyms), accepts=_ACCEPTS[tool.accepts], column_scoped=True, local_only=True,
        row_wise=True,
    )


def add_tool(spec: ToolSpec) -> None:
    if spec.name in TOOLS:
        raise BadRequestError(f"There is a tool called {spec.name} already.")
    register(spec)


def remove_tool(name: str) -> None:
    TOOLS.pop(name, None)
    _EXTENSIONS.pop(name, None)


# ---------------------------------------------------------------- functions


def function_clash(name: str) -> str | None:
    """Why a plugin may not take this function name, or None."""
    from service_transformations.formula.parser import _ALIASES

    lowered = name.lower()
    if lowered in FUNCTIONS or lowered in _ALIASES or lowered in ("if", "ifs"):
        return f"{name.upper()} is a function Pipewright has already; a plugin's functions have names of their own."
    return None


def add_function(plugin: str, function: Any) -> str:
    """Put an SDK ``Function`` in the catalogue and give it its local handler; its name, lowercased."""
    name = function.name.lower()
    clash = function_clash(name)
    if clash:
        raise BadRequestError(clash)
    result = _TYPES[function.returns]
    FUNCTIONS[name] = Signature(name, function.min_args, function.max_args, lambda _args: result, {}, False)

    def handler(args: list[pd.Series], _expr: Any) -> pd.Series:
        index = args[0].index
        out = []
        for row in zip(*(arg.tolist() for arg in args)):
            if any(value is None or (not isinstance(value, (list, dict)) and pd.isna(value)) for value in row):
                out.append(None)
                continue
            try:
                out.append(function.implementation(*(_plain(value) for value in row)))
            except Exception as exc:  # noqa: BLE001 - said where the formula is, naming the plugin
                raise BadRequestError(f"{name.upper()} (from the {plugin} plugin) could not answer for "
                                      f"{row!r}: {exc}") from exc
        return pd.Series(out, index=index, dtype=object).infer_objects()

    HANDLERS[name] = handler
    return name


def remove_function(name: str) -> None:
    FUNCTIONS.pop(name.lower(), None)
    HANDLERS.pop(name.lower(), None)


def check_function(name: str, examples: tuple[tuple[tuple[Any, ...], Any], ...]) -> list[str]:
    """What is wrong with a catalogue function as a formula sees it: [] when nothing.

    Each example is evaluated through the engine; an empty argument in each
    place gives an empty answer; the function declares its type and lowers to
    no database.
    """
    from pipewright_plugin_sdk.checks import same

    from service_transformations.formula.parser import parse_formula

    problems: list[str] = []
    signature = FUNCTIONS[name]
    if signature.sql:
        problems.append(f"{name.upper()} claims SQL a plugin cannot prove here")
    for arguments, answer in examples:
        frame = pd.DataFrame({f"a{i}": [value] for i, value in enumerate(arguments)})
        formula = f"{name}({', '.join(f'[a{i}]' for i in range(len(arguments)))})"
        try:
            got = evaluate(parse_formula(formula, columns=list(frame.columns)), frame).tolist()[0]
        except Exception as exc:  # noqa: BLE001 - reported as the finding
            problems.append(f"{formula} failed: {type(exc).__name__}: {exc}")
            continue
        if not same(answer, _plain(got)):
            problems.append(f"{name.upper()}{tuple(arguments)!r} gave {got!r} in a formula, not {answer!r}")
        for position in range(len(arguments)):
            args = [Literal(None, STRING) if i == position else Literal(_plain(value), _literal_type(value))
                    for i, value in enumerate(arguments)]
            try:
                empty = evaluate(Call(name, tuple(args)), pd.DataFrame({"x": [1]})).tolist()[0]
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{name.upper()} failed on an empty argument: {type(exc).__name__}: {exc}")
                break
            if not (empty is None or (not isinstance(empty, (list, dict)) and pd.isna(empty))):
                problems.append(f"{name.upper()} gave {empty!r} for an empty argument {position + 1}, not empty")
                break
    return problems


def _literal_type(value: Any) -> PWType:
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int):
        return INT64
    if isinstance(value, float):
        return FLOAT64
    return STRING
