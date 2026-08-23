"""Connector implementations.

Importing this module registers every connector, which is the only place the
catalogue is assembled.
"""

from service_connectors.adapters.files import FILE_CONNECTORS
from service_connectors.adapters.nosql import NOSQL_CONNECTORS
from service_connectors.adapters.rest import REST_CONNECTORS
from service_connectors.adapters.saas import SAAS_CONNECTORS
from service_connectors.adapters.sql import SQL_CONNECTORS
from service_connectors.registry import register

for _connector in (
    *SQL_CONNECTORS,
    *REST_CONNECTORS,
    *FILE_CONNECTORS,
    *NOSQL_CONNECTORS,
    *SAAS_CONNECTORS,
):
    register(_connector)

__all__ = [
    "FILE_CONNECTORS",
    "NOSQL_CONNECTORS",
    "REST_CONNECTORS",
    "SAAS_CONNECTORS",
    "SQL_CONNECTORS",
]
