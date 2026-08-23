"""The catalogue of connectors, and validation against what each one declares.

A registry rather than a dispatch table of `if connector_type == ...`: the point
of the SDK is that adding a connector is one registration, not an edit in four
files. The config validation here reads the same spec the UI renders its form
from, so a field the form collects and the validator ignores cannot happen.
"""

from __future__ import annotations

from typing import Any

from shared_python.errors import BadRequestError, NotFoundError

from service_connectors.protocol import Connector, ConnectorSpec

_registry: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    """Add a connector. Registering the same type twice is a programming error."""
    existing = _registry.get(connector.spec.type)
    if existing is not None and existing is not connector:
        raise ValueError(f"A different connector is already registered as '{connector.spec.type}'.")
    _registry[connector.spec.type] = connector
    return connector


def get(connector_type: str) -> Connector:
    connector = _registry.get(connector_type)
    if connector is None:
        raise NotFoundError(
            f"No connector named '{connector_type}'. Available: {', '.join(known_types())}."
        )
    return connector


def known_types() -> list[str]:
    return sorted(_registry)


def specs() -> list[ConnectorSpec]:
    return [connector.spec for connector in sorted(_registry.values(), key=lambda c: c.spec.label)]


def spec_for(connector_type: str) -> ConnectorSpec:
    return get(connector_type).spec


def clear() -> None:
    """Only for tests; the registry is otherwise built once at import."""
    _registry.clear()


def validate_config(connector_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Check a config against its connector's declared fields.

    Returns the config with defaults filled in. Unknown keys are rejected rather
    than ignored: a typo in a field name that silently does nothing is how
    someone spends an afternoon wondering why their port setting had no effect.
    """
    spec = spec_for(connector_type)
    if not isinstance(config, dict):
        raise BadRequestError("Connection config must be an object.")

    known = {field.name: field for field in spec.config_fields}
    unknown = sorted(set(config) - set(known))
    if unknown:
        raise BadRequestError(
            f"{spec.label} has no setting(s) named: {', '.join(unknown)}. "
            f"Expected: {', '.join(sorted(known))}."
        )

    resolved: dict[str, Any] = {}
    missing: list[str] = []

    for name, field in known.items():
        value = config.get(name, field.default)
        if value is None or (isinstance(value, str) and not value.strip()):
            if field.required:
                missing.append(field.label)
                continue
            if field.default is None:
                continue
            value = field.default

        if field.kind == "number":
            value = _as_number(field.label, value)
        elif field.kind == "boolean":
            value = _as_boolean(field.label, value)
        elif field.kind == "select" and str(value) not in field.options:
            raise BadRequestError(
                f"{field.label} must be one of: {', '.join(field.options)}."
            )
        elif isinstance(value, str):
            value = value.strip()

        resolved[name] = value

    if missing:
        raise BadRequestError(f"{spec.label} needs: {', '.join(sorted(missing))}.")

    return resolved


def _as_number(label: str, value: Any) -> int | float:
    if isinstance(value, bool):
        raise BadRequestError(f"{label} must be a number.")
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        return int(text) if text.isdigit() or (text.startswith("-") and text[1:].isdigit()) else float(text)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(f"{label} must be a number.") from exc


def _as_boolean(label: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    raise BadRequestError(f"{label} must be true or false.")


def redact(connector_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """A config safe to log or return over the API."""
    secrets = set(spec_for(connector_type).secret_fields)
    return {
        key: ("********" if key in secrets and value else value) for key, value in config.items()
    }
