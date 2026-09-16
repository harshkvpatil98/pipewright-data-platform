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
from enum import Enum
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

CATEGORIES = (
    "database", "warehouse", "api", "storage", "saas", "nosql", "file",
    "timeseries", "streaming", "lakehouse",
)


class Tier(int, Enum):
    """How much is actually known about whether a connector works.

    With nineteen connectors, "five are unverified" is a footnote somebody reads.
    With two hundred, an undifferentiated list is a lie by omission: it presents
    a connector written from a vendor's documentation as though it carried the
    same weight as one that runs against a real instance on every merge.

    So every connector carries a tier, and the tier is shown wherever a
    connector is chosen and in the output of any run that used it. This is the
    Phase 04 rule -- a declared capability is what works *here*, not what was
    designed -- applied to the catalogue as a whole.
    """

    #: Runs against a real instance in CI on every merge.
    LIVE = 1
    #: Runs against a container or a local fixture in CI.
    CONTAINER = 2
    #: Replays a captured real session; no live credentials involved.
    RECORDED = 3
    #: Written from vendor documentation and never executed. Usable, and said so.
    SPEC_ONLY = 4

    @property
    def label(self) -> str:
        return {
            Tier.LIVE: "Verified",
            Tier.CONTAINER: "Tested",
            Tier.RECORDED: "Recorded",
            Tier.SPEC_ONLY: "Unverified",
        }[self]

    @property
    def badge(self) -> str:
        return {Tier.LIVE: "✅", Tier.CONTAINER: "◑", Tier.RECORDED: "◔", Tier.SPEC_ONLY: "○"}[self]

    @property
    def explanation(self) -> str:
        return {
            Tier.LIVE: "Runs against a real instance in CI on every merge.",
            Tier.CONTAINER: "Runs against a container or local fixture in CI on every merge.",
            Tier.RECORDED: "Tested by replaying a captured real session. Never run live here.",
            Tier.SPEC_ONLY: (
                "Never executed against a real instance here. The configuration is as "
                "the vendor documents it; treat your first run as the real test."
            ),
        }[self]

    @property
    def verified(self) -> bool:
        """True when something actually executed this connector."""
        return self is not Tier.SPEC_ONLY

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
    # How much is known about whether this actually works. Defaults to the
    # weakest claim, so a connector that forgets to say is described as
    # unverified rather than silently promoted.
    tier: Tier = Tier.SPEC_ONLY
    # What backs a tier above 4. Names a test file, so the claim is a citation
    # rather than an assertion -- `test_generators.py` checks the file exists
    # and mentions this connector. A tier system nobody can audit is decoration.
    verified_by: str | None = None
    # Where the connector came from, for the health view: "handwritten",
    # "manifest", "dialect", "matrix".
    origin: str = "handwritten"

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category '{self.category}' for '{self.type}'.")
        unknown = self.capabilities - set(CAPABILITIES)
        if unknown:
            raise ValueError(f"Unknown capabilities on '{self.type}': {sorted(unknown)}")
        if self.tier is not Tier.SPEC_ONLY and not self.verified_by:
            # The invariant lives here rather than in each generator, so a
            # hand-written connector cannot promote itself either.
            raise ValueError(
                f"'{self.type}' claims tier {int(self.tier)} but does not say what "
                "verified it. Set verified_by to the test that exercises it, or "
                "leave the tier at 4."
            )

    @property
    def tier_caveat(self) -> str | None:
        """The sentence an unverified connector attaches to what it produces.

        None for tiers 1-3: a warning that appears regardless of tier is a
        warning people stop reading, which costs the tier system the thing it
        was built for.
        """
        if self.tier.verified:
            return None
        return f"{self.label} is {self.tier.label.lower()}: {self.tier.explanation}"

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
            "tier": int(self.tier),
            "tier_label": self.tier.label,
            "tier_badge": self.tier.badge,
            "tier_explanation": self.tier.explanation,
            "verified": self.tier.verified,
            "verified_by": self.verified_by,
            "origin": self.origin,
        }


def with_tier_note(result: Any, spec: ConnectorSpec) -> Any:
    """Attach the tier caveat to a result, when there is one to attach.

    One function rather than the same sentence built in each connector: the
    caveat has to read identically wherever it appears, and three copies of it
    is three places for one of them to drift or to be forgotten. A connector
    that forgets is the failure mode this exists to prevent -- the roadmap's
    rule is that a run whose source is unverified says so in its *output*, not
    only in the picker somebody saw an hour ago.

    Returns the result: `TestResult` is frozen, so a note means a new one.
    """
    note = spec.tier_caveat
    if note is None:
        return result
    if isinstance(result, TestResult):
        if not result.success:
            # A failed test has a reason of its own; the tier is not it.
            return result
        return TestResult(
            success=result.success,
            message=result.message,
            latency_ms=result.latency_ms,
            server_version=result.server_version,
            warnings=[*result.warnings, note],
        )
    result.warnings.append(note)
    return result


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
