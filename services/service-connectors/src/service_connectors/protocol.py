"""One interface for every source and destination.

Before this, adding a connector meant touching the extraction service, the
config validation, the UI form, and the test suite -- four places, each with its
own idea of what a connector is. The point of an SDK is that the fifth connector
costs a fraction of the first.

The design decisions worth stating:

**Capabilities are declared, not discovered.** A connector says up front whether
it can be listed, read incrementally, or written back to. Callers branch on the
declaration rather than calling a method and catching `NotImplementedError`,
which means the UI can grey out a button instead of offering one that fails.

**Config fields are part of the spec.** A connector describes its own settings --
name, kind, whether it is a secret -- so the form that collects them is
generated. A hand-written form per connector is how the tenth one ends up
missing a field.

**Secrets are named by the spec.** Encryption at rest and redaction in logs both
read the same list, so there is one answer to "is this field sensitive" rather
than one per layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# What a connector can do. Anything not declared is assumed absent.
CAPABILITIES = (
    "test",  # can verify its own configuration
    "discover",  # can list what is available without being told
    "schema",  # can describe a stream's columns before reading it
    "read",  # can pull rows
    "incremental",  # can pull only what changed since a cursor
    "write",  # can push rows back (reverse ETL)
)

CATEGORIES = ("database", "warehouse", "api", "storage", "saas", "nosql", "file")

FIELD_KINDS = ("string", "secret", "number", "boolean", "select", "text")

WRITE_MODES = ("replace", "append", "upsert")


@dataclass(frozen=True)
class ConfigField:
    """One setting a connector needs, described well enough to render a form."""

    name: str
    label: str
    kind: str = "string"
    required: bool = True
    default: Any = None
    help: str | None = None
    options: tuple[str, ...] = ()
    placeholder: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"Unknown field kind '{self.kind}' on '{self.name}'.")
        if self.kind == "select" and not self.options:
            raise ValueError(f"Select field '{self.name}' needs options.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "default": self.default,
            "help": self.help,
            "options": list(self.options),
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class ConnectorSpec:
    """Everything about a connector that is true before it is configured."""

    type: str
    label: str
    category: str
    description: str
    config_fields: tuple[ConfigField, ...] = ()
    capabilities: frozenset[str] = frozenset({"test", "read"})
    # The pip package that has to be installed for this connector to work at
    # all. Declared so a missing driver is a clear message rather than an
    # ImportError somewhere deep in a run.
    driver_package: str | None = None
    documentation_url: str | None = None
    # False when the driver this connector needs is not installed here. The
    # capability set then narrows to what actually works, so `supports()` never
    # promises something a caller would only discover by trying it.
    available: bool = True
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category '{self.category}' for '{self.type}'.")
        unknown = self.capabilities - set(CAPABILITIES)
        if unknown:
            raise ValueError(f"Unknown capabilities on '{self.type}': {sorted(unknown)}")

    @property
    def secret_fields(self) -> tuple[str, ...]:
        """Fields that must be encrypted at rest and never logged."""
        return tuple(field.name for field in self.config_fields if field.kind == "secret")

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.config_fields if field.required)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "config_fields": [field.to_dict() for field in self.config_fields],
            "capabilities": sorted(self.capabilities),
            "secret_fields": list(self.secret_fields),
            "driver_package": self.driver_package,
            "documentation_url": self.documentation_url,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class TestResult:
    # pytest collects any class named Test*; this is a result, not a test case.
    __test__ = False

    success: bool
    message: str
    latency_ms: float | None = None
    server_version: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "server_version": self.server_version,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StreamRef:
    """Something readable: a table, an endpoint, a file pattern, a collection."""

    name: str
    # A namespace when the source has one -- a schema, a bucket, a database.
    namespace: str | None = None
    kind: str = "table"
    # Anything the connector needs to read this back that is not in the name.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class StreamColumn:
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
        }


@dataclass
class ReadResult:
    """Rows, plus enough to ask for the next batch."""

    dataframe: Any  # pandas.DataFrame, typed loosely to keep pandas out of the protocol
    row_count: int
    truncated: bool = False
    # Where to resume from next time, for connectors that support it.
    next_cursor: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class WriteResult:
    rows_written: int
    mode: str
    message: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_written": self.rows_written,
            "mode": self.mode,
            "message": self.message,
            "warnings": list(self.warnings),
        }


@runtime_checkable
class Connector(Protocol):
    """What every connector implements.

    Only `spec` and `test` are mandatory. Everything else is gated on the
    capability the spec declares, so a read-only connector simply does not
    declare `write` and no caller ever asks.
    """

    spec: ConnectorSpec

    def test(self, config: dict[str, Any]) -> TestResult: ...


class ConnectorError(Exception):
    """A connector could not do what was asked, for a reason worth showing."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        # Whether trying the same thing again could plausibly work: a rate limit
        # yes, a bad password no. Callers use it to decide about retrying.
        self.retryable = retryable
