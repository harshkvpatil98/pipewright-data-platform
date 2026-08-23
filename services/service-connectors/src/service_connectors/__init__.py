"""The connector SDK: one interface for every source and destination."""

from service_connectors import adapters  # noqa: F401  - registers the catalogue
from service_connectors.conformance import check_live, check_spec
from service_connectors.protocol import (
    ConfigField,
    Connector,
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    WriteResult,
)
from service_connectors.registry import get, register, specs, validate_config
from service_connectors.router import build_router
from service_connectors.status import get_service_status

__all__ = [
    "ConfigField",
    "Connector",
    "ConnectorError",
    "ConnectorSpec",
    "ReadResult",
    "StreamColumn",
    "StreamRef",
    "TestResult",
    "WriteResult",
    "build_router",
    "check_live",
    "check_spec",
    "get",
    "get_service_status",
    "register",
    "specs",
    "validate_config",
]
