"""SQL databases and warehouses, behind the SDK interface.

The three databases Pipewright already spoke to are not reimplemented here --
`service_extraction.connectors.sql_database` works and is well covered, so this
adapts it rather than replacing it. That is the only reason this package depends
on the extraction service instead of the other way round; if the SQL code ever
moves, this is the one file that has to follow it.

The warehouses are declared but not driver-backed. Declaring them is not
pretending: the spec is what the UI renders and what config validation enforces,
and `test()` says plainly which package is missing rather than failing somewhere
deep in a run with an ImportError.
"""

from __future__ import annotations

import time
from typing import Any

from shared_python.errors import ApplicationError

from service_connectors.protocol import (
    ConfigField,
    Connector,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
)

# Every SQL backend needs the same five things, so the fields are built once.
def _server_fields(default_port: int, *, database_label: str = "Database") -> tuple[ConfigField, ...]:
    return (
        ConfigField("host", "Host", placeholder="db.internal"),
        ConfigField("port", "Port", kind="number", required=False, default=default_port),
        ConfigField("database", database_label),
        ConfigField("username", "Username"),
        ConfigField("password", "Password", kind="secret"),
        ConfigField(
            "sslmode",
            "SSL mode",
            kind="select",
            required=False,
            options=("disable", "require", "verify-ca", "verify-full"),
            default="require",
            help="Whether to insist the connection is encrypted.",
        ),
    )


class SqlConnector:
    """One of the databases the extraction service already speaks to."""

    def __init__(self, spec: ConnectorSpec, backend: str) -> None:
        self.spec = spec
        # The name `sql_database` knows this database by, which is not always
        # the same as the connector type the UI shows.
        self._backend = backend

    def _config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in config.items() if value is not None}

    def test(self, config: dict[str, Any]) -> TestResult:
        from service_extraction.connectors import sql_database

        started = time.perf_counter()
        try:
            result = sql_database.test_connection(self._backend, self._config(config))
        except ApplicationError as exc:
            return TestResult(success=False, message=str(exc.detail))
        return TestResult(
            success=result.success,
            message=result.message,
            latency_ms=result.latency_ms or round((time.perf_counter() - started) * 1000, 2),
            server_version=result.server_version,
            warnings=list(result.warnings),
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        from service_extraction.connectors import sql_database

        return [
            StreamRef(name=table.name, namespace=table.schema, kind=table.kind)
            for table in sql_database.list_tables(self._backend, self._config(config))
        ]

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        from service_extraction.connectors import sql_database

        return [
            StreamColumn(
                name=column.name,
                data_type=column.data_type,
                nullable=column.nullable,
                primary_key=column.primary_key,
            )
            for column in sql_database.list_columns(
                self._backend, self._config(config), table=stream.name, schema=stream.namespace
            )
        ]

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        from service_extraction.connectors import sql_database

        query = sql_database.build_table_query(
            self._backend, table=stream.name, schema=stream.namespace
        )
        result = sql_database.read_dataframe(
            self._backend, self._config(config), query=query, max_rows=limit
        )
        return ReadResult(
            dataframe=result.dataframe,
            row_count=result.row_count,
            truncated=result.truncated,
            warnings=list(result.warnings),
        )


class UnavailableConnector:
    """A connector whose driver is not installed.

    It exists so the catalogue is honest about what the platform is designed to
    reach, and so the failure is one clear sentence at configuration time rather
    than an ImportError in the middle of a scheduled run at 3am.
    """

    def __init__(self, spec: ConnectorSpec) -> None:
        self.spec = spec

    def test(self, _config: dict[str, Any]) -> TestResult:
        return TestResult(
            success=False,
            message=(
                self.spec.unavailable_reason
                or f"{self.spec.label} is not available on this deployment."
            )
            + " Install it and restart the service to use this connector.",
        )


POSTGRES = SqlConnector(
    ConnectorSpec(
        type="postgresql",
        label="PostgreSQL",
        category="database",
        description="Read tables and views from a PostgreSQL database.",
        config_fields=_server_fields(5432),
        capabilities=frozenset({"test", "discover", "schema", "read", "incremental"}),
    ),
    backend="postgresql",
)

MYSQL = SqlConnector(
    ConnectorSpec(
        type="mysql",
        label="MySQL",
        category="database",
        description="Read tables and views from a MySQL or MariaDB database.",
        config_fields=_server_fields(3306),
        capabilities=frozenset({"test", "discover", "schema", "read", "incremental"}),
    ),
    backend="mysql",
)

SQLITE = SqlConnector(
    ConnectorSpec(
        type="sqlite",
        label="SQLite",
        category="database",
        description="Read tables from a SQLite file on the server's filesystem.",
        config_fields=(
            ConfigField(
                "file_path",
                "File path",
                help="An absolute path the platform can read.",
                placeholder="/data/warehouse.db",
            ),
        ),
        capabilities=frozenset({"test", "discover", "schema", "read", "incremental"}),
    ),
    backend="sqlite",
)


def _warehouse(
    connector_type: str,
    label: str,
    description: str,
    driver_package: str,
    fields: tuple[ConfigField, ...],
) -> UnavailableConnector:
    return UnavailableConnector(
        ConnectorSpec(
            type=connector_type,
            label=label,
            category="warehouse",
            description=description,
            config_fields=fields,
            # Only `test`, because only `test` works: it reports the missing
            # driver. Declaring `read` here would make `supports("read")` a
            # promise the connector cannot keep, and the whole point of
            # declared capabilities is that callers can trust them.
            capabilities=frozenset({"test"}),
            driver_package=driver_package,
            available=False,
            unavailable_reason=(
                f"{label} needs the '{driver_package}' package, which is not installed "
                "on this deployment."
            ),
        )
    )


SNOWFLAKE = _warehouse(
    "snowflake",
    "Snowflake",
    "Read from a Snowflake warehouse.",
    "snowflake-sqlalchemy",
    (
        ConfigField("account", "Account", placeholder="ab12345.eu-west-1"),
        ConfigField("warehouse", "Warehouse"),
        ConfigField("database", "Database"),
        ConfigField("schema", "Schema", required=False, default="PUBLIC"),
        ConfigField("username", "Username"),
        ConfigField("password", "Password", kind="secret"),
        ConfigField("role", "Role", required=False),
    ),
)

BIGQUERY = _warehouse(
    "bigquery",
    "BigQuery",
    "Read from a Google BigQuery dataset.",
    "sqlalchemy-bigquery",
    (
        ConfigField("project", "Project id"),
        ConfigField("dataset", "Dataset"),
        ConfigField(
            "credentials_json",
            "Service account JSON",
            kind="secret",
            help="The whole key file, pasted in.",
        ),
    ),
)

REDSHIFT = _warehouse(
    "redshift",
    "Redshift",
    "Read from an Amazon Redshift cluster.",
    "sqlalchemy-redshift",
    _server_fields(5439),
)

SQLSERVER = _warehouse(
    "sqlserver",
    "SQL Server",
    "Read from a Microsoft SQL Server database.",
    "pyodbc",
    _server_fields(1433),
)

ORACLE = _warehouse(
    "oracle",
    "Oracle",
    "Read from an Oracle database.",
    "oracledb",
    _server_fields(1521, database_label="Service name"),
)

SQL_CONNECTORS: tuple[Connector, ...] = (
    POSTGRES,
    MYSQL,
    SQLITE,
    SNOWFLAKE,
    BIGQUERY,
    REDSHIFT,
    SQLSERVER,
    ORACLE,
)
