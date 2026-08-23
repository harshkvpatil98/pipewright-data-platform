"""Contracts for the connector catalogue."""

from __future__ import annotations

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


class ConnectorCatalogResponse(BaseModel):
    items: list[ConnectorSpecRead]
    categories: list[str]


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
