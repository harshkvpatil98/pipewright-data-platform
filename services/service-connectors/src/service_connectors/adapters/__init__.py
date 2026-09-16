"""Connector implementations.

Importing this module registers every connector, which is the only place the
catalogue is assembled.
"""

from service_connectors.adapters.files import FILE_CONNECTORS
from service_connectors.adapters.nosql import NOSQL_CONNECTORS
from service_connectors.adapters.protocols import PROTOCOL_CONNECTORS
from service_connectors.adapters.rest import REST_CONNECTORS
from service_connectors.adapters.saas import SAAS_CONNECTORS
from service_connectors.adapters.sql import SQL_CONNECTORS
from service_connectors.registry import register

_HANDWRITTEN = (
    *SQL_CONNECTORS,
    *REST_CONNECTORS,
    *FILE_CONNECTORS,
    *NOSQL_CONNECTORS,
    *SAAS_CONNECTORS,
    *PROTOCOL_CONNECTORS,
)

for _connector in _HANDWRITTEN:
    register(_connector)

# Generated connectors come second, so a hand-written one always wins the name.
# The hand-written ones are the tested ones; a generated entry quietly shadowing
# PostgreSQL would replace something proven with something declared.
from service_connectors.generators import REPORT, build_all  # noqa: E402

_GENERATED, _REPORT = build_all({connector.spec.type for connector in _HANDWRITTEN})
for _connector in _GENERATED:
    register(_connector)

REPORT.generated.update(_REPORT.generated)
REPORT.skipped.extend(_REPORT.skipped)
REPORT.failed.extend(_REPORT.failed)

__all__ = [
    "REPORT",
    "FILE_CONNECTORS",
    "NOSQL_CONNECTORS",
    "PROTOCOL_CONNECTORS",
    "REST_CONNECTORS",
    "SAAS_CONNECTORS",
    "SQL_CONNECTORS",
]
