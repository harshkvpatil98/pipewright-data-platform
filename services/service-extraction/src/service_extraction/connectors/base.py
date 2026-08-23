"""Connector-facing value objects shared by every extraction backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Sensitive keys are encrypted at rest and must never reach logs or API responses.
SENSITIVE_CONFIG_FIELDS: tuple[str, ...] = ("password",)

SUPPORTED_CONNECTOR_TYPES: tuple[str, ...] = ("postgresql", "mysql", "sqlite")

# Load strategies a saved extraction job can use.
LOAD_MODES: tuple[str, ...] = ("full_refresh", "incremental_append", "incremental_merge")


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    message: str
    latency_ms: float | None = None
    server_version: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableRef:
    """A discoverable relation on the remote database."""

    schema: str | None
    name: str
    kind: str  # "table" | "view"

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass(frozen=True)
class DiscoveredColumn:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of pulling rows from a remote database."""

    dataframe: Any  # pandas.DataFrame; typed loosely to keep pandas out of this module
    row_count: int
    truncated: bool
    warnings: list[str] = field(default_factory=list)
