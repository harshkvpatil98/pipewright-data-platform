"""Schema validation for orchestrator artifacts.

`jsonschema` is used when it is importable, and the bundled validator otherwise.
The fallback is deliberate rather than lazy: this tool must install into a
throwaway virtualenv that shares nothing with the product's dependency tree, and
the schemas here are authored in a small, fixed subset of JSON Schema. The
subset is exactly what the two provider CLIs accept in strict structured-output
mode, so there is nothing in these documents the fallback cannot evaluate.
"""

from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - exercised by whichever branch the host provides
    import jsonschema as _jsonschema
except ImportError:  # pragma: no cover
    _jsonschema = None


class SchemaError(ValueError):
    """Raised when a document does not satisfy its schema.

    Carries every failure, not just the first: a model that got three fields
    wrong should be told about three fields, not asked three times.
    """

    def __init__(self, schema_id: str, errors: list[str]) -> None:
        self.schema_id = schema_id
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"document does not satisfy {schema_id}:\n{joined}")


_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "integer":
        # bool is a subclass of int; a boolean is not an integer here.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    py = _TYPES.get(expected)
    if py is None:
        return True  # unknown keyword: do not invent a failure
    return isinstance(value, py)


def _resolve(schema: Any, root: dict) -> dict:
    """Follow a local `$ref` (`#/$defs/Name`). Remote refs are not used."""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported, got {ref!r}")
        node: Any = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
        seen += 1
        if seen > 32:
            raise ValueError(f"$ref cycle at {ref!r}")
    return schema


def _walk(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected the constant {schema['const']!r}, got {value!r}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']!r}")
        return

    if "anyOf" in schema:
        branches: list[list[str]] = []
        for branch in schema["anyOf"]:
            sub: list[str] = []
            _walk(value, branch, root, path, sub)
            if not sub:
                break
            branches.append(sub)
        else:
            errors.append(
                f"{path}: matched none of {len(schema['anyOf'])} alternatives "
                f"({'; '.join(b[0] for b in branches if b)})"
            )
            return

    expected = schema.get("type")
    if expected is not None:
        options = [expected] if isinstance(expected, str) else list(expected)
        if not any(_type_matches(value, option) for option in options):
            errors.append(
                f"{path}: expected type {'|'.join(options)}, got "
                f"{type(value).__name__}"
            )
            return

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")
        for key, sub_schema in properties.items():
            if key in value:
                _walk(value[key], sub_schema, root, f"{path}.{key}", errors)

    elif isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _walk(item, item_schema, root, f"{path}[{index}]", errors)
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: needs at least {min_items} items, has {len(value)}")

    elif isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(f"{path}: {value!r} does not match /{pattern}/")
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: shorter than {min_length} characters")

    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: {value} is below the minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: {value} is above the maximum {maximum}")


def validate(document: Any, schema: dict, schema_id: str = "<schema>") -> None:
    """Raise `SchemaError` unless `document` satisfies `schema`."""
    errors: list[str] = []
    if _jsonschema is not None:
        validator = _jsonschema.Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(document), key=str):
            location = "$" + "".join(
                f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path
            )
            errors.append(f"{location}: {error.message}")
    else:
        _walk(document, schema, schema, "$", errors)
    if errors:
        raise SchemaError(schema_id, errors)


def validate_artifact(document: Any, schema_id: str) -> None:
    """Validate against a registered schema, checking `schema_version` first.

    A document carrying the wrong `schema_version` is rejected before the body is
    examined, so a v2 artifact can never be silently read as v1.
    """
    from . import load_schema

    if isinstance(document, dict):
        declared = document.get("schema_version")
        if declared is not None and declared != schema_id:
            raise SchemaError(
                schema_id,
                [f"$.schema_version: document declares {declared!r}, expected {schema_id!r}"],
            )
    validate(document, load_schema(schema_id), schema_id)


def validator_backend() -> str:
    """Which implementation is in use, for `pw-dev doctor`."""
    return "jsonschema" if _jsonschema is not None else "builtin"


__all__ = ["SchemaError", "validate", "validate_artifact", "validator_backend"]
