"""Contracts for the connector catalogue."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConfigFieldRead(BaseModel):
    name: str
    label: str
    kind: Literal["string", "secret", "number", "boolean", "select", "text"]
    required: bool
    default: Any = None
    help: str | None = None
    options: list[str] = Field(default_factory=list)
    placeholder: str | None = None


class ConnectorSpecRead(BaseModel):
    type: str
    label: str
    category: str
    description: str
    config_fields: list[ConfigFieldRead]
    capabilities: list[str]
    secret_fields: list[str]
    driver_package: str | None
    documentation_url: str | None
    available: bool
    unavailable_reason: str | None
    # How much is known about whether this works, and what backs the claim.
    # Sent on every connector so the picker, the config form and the run log
    # all read the same answer.
    tier: int
    tier_label: str
    tier_badge: str
    tier_explanation: str
    verified: bool
    verified_by: str | None = None
    origin: str = "handwritten"


class ConnectorCatalogResponse(BaseModel):
    items: list[ConnectorSpecRead]
    categories: list[str]


class TierSummaryRead(BaseModel):
    tier: int
    label: str
    badge: str
    explanation: str
    count: int
    verified: bool


class CategorySummaryRead(BaseModel):
    category: str
    total: int
    available: int
    verified: int


class MissingPackageRead(BaseModel):
    package: str
    unlocks: int


class ConnectorHealthResponse(BaseModel):
    total: int
    available: int
    verified: int
    tiers: list[TierSummaryRead]
    categories: list[CategorySummaryRead]
    origins: dict[str, int]
    missing_packages: list[MissingPackageRead]
    formats: int
    store_format_combinations: int


class ConnectorUsageRead(BaseModel):
    connector_type: str
    label: str
    tier: int
    tier_label: str
    available: bool
    connections: int
    last_tested_at: str | None = None
    last_test_status: str | None = None
    failing: int


class ConnectorUsageResponse(BaseModel):
    items: list[ConnectorUsageRead]


class FormatRead(BaseModel):
    name: str
    label: str
    extensions: list[str]
    typed: bool
    writable: bool
    description: str


class FormatCatalogResponse(BaseModel):
    items: list[FormatRead]
    compressions: list[str]


class ConnectorTestRequest(BaseModel):
    connector_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
    server_version: str | None = None
    warnings: list[str] = Field(default_factory=list)


class StreamRead(BaseModel):
    name: str
    namespace: str | None
    kind: str
    qualified_name: str
    detail: dict[str, Any]


class StreamListResponse(BaseModel):
    connector_type: str
    items: list[StreamRead]


class ConformanceResponse(BaseModel):
    connector_type: str
    ok: bool
    passed: list[str]
    failures: list[str]
    skipped: list[str]


# --------------------------------------------------------- the schema watch


class WatchedStreamRead(BaseModel):
    connection_id: str
    connector_type: str
    stream: str
    columns: int
    source: str
    observed_at: str | None = None
    last_severity: str
    last_summary: str | None = None
    drift_count: int


class WatchStatusResponse(BaseModel):
    items: list[WatchedStreamRead]
    #: Connectors whose schema can be compared without a live credential --
    #: a manifest that declares its columns. Useful on its own: it is the
    #: answer to "what could this deployment watch at all".
    describable: list[str]


class SweepRequest(BaseModel):
    """Narrow a sweep, or rehearse one."""

    connection_id: uuid.UUID | None = None
    #: False runs the comparison and records nothing and opens nothing. The
    #: rehearsal matters because the first sweep of a busy project can open a
    #: lot of incidents, and somebody should be able to look first.
    apply: bool = True


class StreamOutcomeRead(BaseModel):
    connection_id: str
    connection_name: str
    connector_type: str
    stream: str
    checked: bool
    severity: str
    summary: str
    added_columns: list[str] = Field(default_factory=list)
    removed_columns: list[str] = Field(default_factory=list)
    type_changes: list[dict[str, str]] = Field(default_factory=list)
    skipped_reason: str = ""
    first_look: bool = False
    incident_id: str | None = None
    source: str


class SkippedConnectionRead(BaseModel):
    connection_id: str
    name: str
    reason: str


class SweepResponse(BaseModel):
    checked_at: str
    connections: int
    streams_checked: int
    streams_skipped: int
    drifted: int
    breaking: int
    incidents: list[str] = Field(default_factory=list)
    skipped_connections: list[SkippedConnectionRead] = Field(default_factory=list)
    #: Connections with more streams than the per-connection limit. Reported
    #: separately from `skipped_connections` because "we looked at some of it"
    #: and "we looked at none of it" deserve different reactions.
    truncated: list[dict[str, Any]] = Field(default_factory=list)
    results: list[StreamOutcomeRead] = Field(default_factory=list)
