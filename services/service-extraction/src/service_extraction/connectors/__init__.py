"""Extraction connectors.

Every supported source database speaks SQLAlchemy, so `sql_database` is the only
backend today. New non-SQL sources (REST, object storage) would add a sibling
module exposing the same test/discover/read surface.
"""

from service_extraction.connectors import sql_database
from service_extraction.connectors.base import (
    LOAD_MODES,
    SENSITIVE_CONFIG_FIELDS,
    SUPPORTED_CONNECTOR_TYPES,
    ConnectionTestResult,
    DiscoveredColumn,
    ExtractionResult,
    TableRef,
)

__all__ = [
    "LOAD_MODES",
    "SENSITIVE_CONFIG_FIELDS",
    "SUPPORTED_CONNECTOR_TYPES",
    "ConnectionTestResult",
    "DiscoveredColumn",
    "ExtractionResult",
    "TableRef",
    "sql_database",
]
