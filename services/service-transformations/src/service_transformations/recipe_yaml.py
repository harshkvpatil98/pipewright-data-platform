"""Recipes as code.

A recipe is a list of steps, and steps are already JSON. So why a separate
serialisation? Because JSON does not diff. A pull request showing

    -      value: 'eu'
    +      value: 'emea'

is reviewable; the same change as a reformatted JSON blob is not. That is the
whole point of this module: recipes live in git alongside application code, get
reviewed like code, and a reviewer can see what changed.

**Lossless in both directions, and tested that way.** `to_yaml(from_yaml(text))`
must give back the same text, and `from_yaml(to_yaml(steps))` the same steps.
Anything that cannot survive the round trip is refused when it goes in rather
than silently altered on the way out -- a recipe that quietly loses a setting is
worse than one that will not save.
"""

from __future__ import annotations

from typing import Any

import yaml

from shared_python.errors import BadRequestError

from service_transformations.contracts import SUPPORTED_TRANSFORMATION_STEP_TYPES

#: Bumped when the shape changes in a way an older reader cannot handle.
FORMAT_VERSION = 1

#: Refused rather than truncated. A recipe this long is a program.
MAX_STEPS = 500


class _Dumper(yaml.SafeDumper):
    """Block style throughout, so a diff is one change per line."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: FBT001,FBT002
        # PyYAML indents list items under their key only when asked; without
        # this, sequences sit at the parent's indentation and read badly.
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.Dumper, value: str):
    """Multi-line strings as literal blocks -- an SQL snippet stays readable."""
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _represent_str)


def to_yaml(
    steps: list[dict[str, Any]],
    *,
    name: str | None = None,
    description: str | None = None,
    dataset: str | None = None,
) -> str:
    """Render a recipe as reviewable YAML."""
    document: dict[str, Any] = {"version": FORMAT_VERSION}
    if name:
        document["name"] = name
    if description:
        document["description"] = description
    if dataset:
        document["dataset"] = dataset
    document["steps"] = [_step_out(step, index) for index, step in enumerate(steps, start=1)]

    return yaml.dump(
        document,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )


def from_yaml(text: str) -> dict[str, Any]:
    """Read a recipe back. Raises with something actionable on bad input."""
    if not isinstance(text, str) or not text.strip():
        raise BadRequestError("There is no recipe to read.")

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # PyYAML's message includes the line and column, which is the useful
        # half; the exception class name is not.
        raise BadRequestError(f"That is not valid YAML: {exc}") from exc

    if document is None:
        raise BadRequestError("There is no recipe to read.")
    if not isinstance(document, dict):
        raise BadRequestError(
            "A recipe is a mapping with a `steps:` list, not a "
            f"{type(document).__name__}."
        )

    version = document.get("version", FORMAT_VERSION)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise BadRequestError(
            f"This recipe says it is version {version}; this platform reads up "
            f"to version {FORMAT_VERSION}."
        )

    unknown = sorted(set(document) - {"version", "name", "description", "dataset", "steps"})
    if unknown:
        raise BadRequestError(
            f"A recipe does not have: {', '.join(unknown)}. "
            "Allowed: name, description, dataset, steps."
        )

    raw_steps = document.get("steps")
    if raw_steps is None:
        raise BadRequestError("A recipe needs a `steps:` list, even if it is empty.")
    if not isinstance(raw_steps, list):
        raise BadRequestError("`steps:` must be a list.")
    if len(raw_steps) > MAX_STEPS:
        raise BadRequestError(
            f"That recipe has {len(raw_steps)} steps; the limit is {MAX_STEPS}."
        )

    return {
        "version": version,
        "name": document.get("name"),
        "description": document.get("description"),
        "dataset": document.get("dataset"),
        "steps": [_step_in(step, index) for index, step in enumerate(raw_steps, start=1)],
    }


def steps_from_yaml(text: str) -> list[dict[str, Any]]:
    """Just the steps, in the shape the executor takes."""
    return from_yaml(text)["steps"]


def _step_out(step: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise BadRequestError(f"Step {index} is not an object.")
    step_type = step.get("step_type") or step.get("type")
    if not step_type:
        raise BadRequestError(f"Step {index} has no step type.")

    config = step.get("config") or {}
    if not isinstance(config, dict):
        raise BadRequestError(f"Step {index}'s config is not an object.")

    # `tool` steps name the tool in their config; hoisting it to the top makes
    # the file read as a list of what happens rather than a list of "tool".
    rendered: dict[str, Any] = {"step": str(step_type)}
    remaining = dict(config)
    if step_type == "tool" and isinstance(remaining.get("tool"), str):
        rendered["tool"] = remaining.pop("tool")
    if step.get("name"):
        rendered["name"] = str(step["name"])
    if remaining:
        rendered["with"] = _plain(remaining, index)
    return rendered


def _step_in(step: Any, index: int) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise BadRequestError(
            f"Step {index} is a {type(step).__name__}; each step is a mapping "
            "with a `step:` key."
        )

    unknown = sorted(set(step) - {"step", "tool", "name", "with"})
    if unknown:
        # Name the shape, not just the stray keys: the most common mistake is
        # the API's `type:`/`config:` spelling, which reads as reasonable YAML
        # and gets nowhere without this sentence.
        raise BadRequestError(
            f"Step {index} does not have: {', '.join(unknown)}. A step is written as "
            "`step:` (its name) and `with:` (its settings), optionally `name:`."
        )

    step_type = step.get("step")
    if not isinstance(step_type, str) or not step_type.strip():
        raise BadRequestError(f"Step {index} needs a `step:` naming what it does.")
    if step_type not in SUPPORTED_TRANSFORMATION_STEP_TYPES:
        raise BadRequestError(
            f"Step {index} is a '{step_type}', which this platform does not have. "
            f"Known steps: {', '.join(sorted(SUPPORTED_TRANSFORMATION_STEP_TYPES))}."
        )

    config = step.get("with") or {}
    if not isinstance(config, dict):
        raise BadRequestError(f"Step {index}'s `with:` is not a mapping.")
    config = dict(config)

    tool = step.get("tool")
    if tool is not None:
        if step_type != "tool":
            raise BadRequestError(
                f"Step {index} names a tool but is a '{step_type}' step."
            )
        config["tool"] = str(tool)
    elif step_type == "tool":
        raise BadRequestError(f"Step {index} is a tool step but does not say which tool.")

    result: dict[str, Any] = {"step_type": step_type, "config": config}
    if step.get("name"):
        result["name"] = str(step["name"])
    return result


#: What YAML can carry without changing. `to_yaml` refuses anything else rather
#: than emitting a Python-specific tag that only this platform can read back.
_PLAIN_TYPES = (str, int, float, bool)


def _plain(value: Any, index: int, path: str = "") -> Any:
    if value is None or isinstance(value, _PLAIN_TYPES):
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BadRequestError(
                    f"Step {index} has a setting whose name is a "
                    f"{type(key).__name__}; YAML keys have to be text."
                )
            out[key] = _plain(item, index, f"{path}.{key}" if path else key)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(item, index, f"{path}[{position}]") for position, item in enumerate(value)]
    raise BadRequestError(
        f"Step {index} has a setting ({path or 'unnamed'}) of type "
        f"{type(value).__name__}, which cannot be written as YAML. "
        "Recipes hold text, numbers, true/false, lists and mappings."
    )
