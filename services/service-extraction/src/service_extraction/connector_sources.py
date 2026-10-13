"""Importing from any connector in the SDK that can read.

The import service grew up around three SQL databases, driven directly so
that queries, cursor columns and pushdown could work. Every other connector
in the catalogue (REST and GraphQL APIs, SaaS apps, S3 and other storage,
files on the server, NoSQL stores) reads through the connector SDK, and this
module is the one place the import service talks to it:

- the connection's settings are validated against the connector's own
  declared fields, and its declared secret fields are encrypted at rest;
- test, list (when the connector can discover) and read go through the
  connector, and its errors read as plain messages;
- a read keeps the connector's tier note, so an unverified connector says so
  in the run it produced.

SQL databases stay on their own path; `is_sql` decides which is which.
"""

from __future__ import annotations

from typing import Any

from shared_python.errors import BadRequestError

from service_extraction.connectors.base import SENSITIVE_CONFIG_FIELDS, SUPPORTED_CONNECTOR_TYPES


def is_sql(connector_type: str) -> bool:
    return connector_type in SUPPORTED_CONNECTOR_TYPES


def _connector(connector_type: str):
    from service_connectors import get

    return get(connector_type)


def spec(connector_type: str):
    return _connector(connector_type).spec


def secret_fields(connector_type: str) -> tuple[str, ...]:
    if is_sql(connector_type):
        return SENSITIVE_CONFIG_FIELDS
    try:
        return tuple(spec(connector_type).secret_fields)
    except Exception:  # noqa: BLE001 - an unknown type has nothing declared secret
        return ()


def validate(connector_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Settings checked against what the connector declares, defaults filled in."""
    from service_connectors import validate_config

    declared = spec(connector_type)
    if not declared.available:
        raise BadRequestError(declared.unavailable_reason or f"{declared.label} is not available here.")
    if not declared.supports("read"):
        raise BadRequestError(f"{declared.label} can be connected to but not imported from yet.")
    return validate_config(connector_type, config)


def _error(connector_type: str, exc: Exception) -> BadRequestError:
    from service_connectors import ConnectorError

    message = exc.message if isinstance(exc, ConnectorError) else str(exc).splitlines()[0][:300] if str(exc) else ""
    label = spec(connector_type).label
    return BadRequestError(message or f"{label} could not be read.")


def test(connector_type: str, config: dict[str, Any]):
    try:
        return _connector(connector_type).test(config)
    except Exception as exc:  # noqa: BLE001 - a failed test is a result, not an error
        from service_connectors import TestResult

        return TestResult(success=False, message=_error(connector_type, exc).detail)


def can_list(connector_type: str) -> bool:
    return spec(connector_type).supports("discover")


def can_resume(connector_type: str) -> bool:
    """True when the connector can read only what is new since last time."""
    return spec(connector_type).supports("incremental")


def discover(connector_type: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """What the connection can import, as stream references (plain dicts)."""
    if not can_list(connector_type):
        return []
    try:
        streams = _connector(connector_type).discover(config)
    except Exception as exc:  # noqa: BLE001
        raise _error(connector_type, exc) from exc
    return [stream.to_dict() for stream in streams]


def stream_ref(stream: dict[str, Any] | None):
    """The StreamRef a stored stream stands for; None means "everything it returns"."""
    if not stream:
        return None
    from service_connectors import StreamRef

    return StreamRef(
        name=str(stream.get("name") or ""),
        namespace=stream.get("namespace"),
        kind=str(stream.get("kind") or "table"),
        detail=dict(stream.get("detail") or {}),
    )


def read(connector_type: str, config: dict[str, Any], stream: dict[str, Any] | None, *, limit: int, cursor: str | None = None):
    connector = _connector(connector_type)
    try:
        return connector.read(config, stream_ref(stream), limit=limit, cursor=cursor)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a message people can act on
        raise _error(connector_type, exc) from exc


def stream_label(stream: dict[str, Any] | None) -> str:
    if not stream:
        return "everything it returns"
    namespace = stream.get("namespace")
    return f"{namespace}.{stream.get('name')}" if namespace else str(stream.get("name"))
