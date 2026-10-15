"""Recipe parameters: values chosen per run, written {{name}} in any setting (E1).

A recipe declares its parameters (a name, a label, a kind, a default) and any
step setting can use them: ``{{since}}`` as a whole setting takes the value
in its own kind (a number stays a number), and inside text, as in
``orders_{{region}}``, it is written in. A person running the recipe, a
schedule, a workflow or the API gives values; the defaults fill the rest.

Parameters are resolved before anything else happens to the steps, so a run
records, and a replay repeats, the steps exactly as they ran, and the kept
results of one set of values are never served for another.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from shared_python.errors import BadRequestError
from shared_python.words import listing

Kind = Literal["text", "number", "whole number", "date", "true or false"]
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
MAX_PARAMETERS = 50


class RecipeParameter(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    label: str | None = Field(default=None, max_length=120)
    kind: Kind = "text"
    default: Any = None
    description: str | None = Field(default=None, max_length=400)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("A parameter's name is letters, numbers and _, starting with a letter: since, region_code.")
        return value


def validate(parameters: list[dict[str, Any]] | list[RecipeParameter]) -> list[RecipeParameter]:
    items = []
    for given in parameters:
        if isinstance(given, RecipeParameter):
            items.append(given)
            continue
        try:
            items.append(RecipeParameter.model_validate(given))
        except ValidationError as exc:
            said = str(exc.errors()[0].get("msg", "")).removeprefix("Value error, ").rstrip(".")
            raise BadRequestError(f"A parameter is not right: {said}.") from exc
    if len(items) > MAX_PARAMETERS:
        raise BadRequestError(f"A recipe takes up to {MAX_PARAMETERS} parameters.")
    names = [p.name for p in items]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise BadRequestError(f"Two parameters are called {listing(repeated)}.")
    for parameter in items:
        if parameter.default is not None and parameter.default != "":
            parameter.default = typed(parameter, parameter.default)
    return items


def typed(parameter: RecipeParameter, value: Any) -> Any:
    """A value in the parameter's own kind, or a plain refusal."""
    label = parameter.label or parameter.name
    if parameter.kind == "text":
        return str(value)
    if parameter.kind in ("number", "whole number"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise BadRequestError(f"{label} is a number, not {value!r}.") from None
        if parameter.kind == "whole number":
            if not number.is_integer():
                raise BadRequestError(f"{label} is a whole number, not {value!r}.")
            return int(number)
        return number
    if parameter.kind == "date":
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            raise BadRequestError(f"{label} is a date written as 2026-10-16, not {value!r}.") from None
    token = str(value).strip().lower()
    if token in ("true", "yes", "1"):
        return True
    if token in ("false", "no", "0"):
        return False
    raise BadRequestError(f"{label} is true or false, not {value!r}.")


def used(steps: list[dict[str, Any]]) -> set[str]:
    """Every parameter name the steps refer to."""
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            found.update(PLACEHOLDER.findall(value))
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    for step in steps:
        visit(step.get("config") or {})
    return found


def values_for(declared: list[RecipeParameter], given: dict[str, Any] | None) -> dict[str, Any]:
    given = dict(given or {})
    known = {p.name: p for p in declared}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise BadRequestError(f"This recipe has no parameter called {listing(unknown)}. "
                              f"It has: {listing(sorted(known)) or 'none'}.")
    values: dict[str, Any] = {}
    for name, parameter in known.items():
        if name in given and given[name] not in (None, ""):
            values[name] = typed(parameter, given[name])
        elif parameter.default not in (None, ""):
            values[name] = parameter.default
    return values


def resolve(steps: list[dict[str, Any]], declared: list[dict[str, Any]] | None,
            given: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The steps with every {{name}} written in."""
    parameters = validate(declared or [])
    referenced = used(steps)
    if not referenced and not given:
        return steps
    values = values_for(parameters, given)
    undeclared = sorted(referenced - {p.name for p in parameters})
    if undeclared:
        raise BadRequestError(f"The steps use {listing(['{{' + n + '}}' for n in undeclared])}, which "
                              f"{'is not a parameter' if len(undeclared) == 1 else 'are not parameters'} of this "
                              "recipe. Add it under Parameters.")
    missing = sorted(name for name in referenced if name not in values)
    if missing:
        raise BadRequestError(f"Give a value for {listing(missing)}: "
                              f"{'it has' if len(missing) == 1 else 'they have'} no default.")

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            whole = PLACEHOLDER.fullmatch(value.strip())
            if whole:
                return values[whole.group(1)]
            return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), value)
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        return value

    return [{**step, "config": fill(step.get("config") or {})} for step in steps]
