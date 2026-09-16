"""Databases as a table, not as a module each.

Every SQL database this platform can reach differs in exactly four ways that
matter to a connector: the SQLAlchemy dialect that drives it, the driver package
that has to be installed, what its connection needs (a host and port, a file
path, an account name), and how it spells "give me a few rows". Everything else
-- introspection, reading, type mapping -- SQLAlchemy already does.

So a database is a `Dialect` entry here rather than a file of its own. Adding
one is six lines, it inherits the conformance suite unchanged, and it cannot
declare a capability the driver does not provide: `availability()` imports the
driver and narrows the spec when it is absent, which is the Phase 04 rule
applied per row of this table.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any

from service_connectors.protocol import ConfigField, ConnectorSpec, Tier

#: The connection shapes. Most databases are one of three.
SERVER = "server"  # host, port, database, username, password
FILE = "file"  # a path on disk
ACCOUNT = "account"  # a cloud account identifier plus a warehouse or project


@dataclass(frozen=True)
class Dialect:
    """One database, described well enough to connect to it."""

    key: str
    label: str
    #: SQLAlchemy's dialect name, e.g. `postgresql+psycopg`.
    driver: str
    #: The pip package that supplies it.
    package: str
    category: str = "database"
    shape: str = SERVER
    default_port: int | None = None
    description: str = ""
    docs_url: str | None = None
    #: How this dialect limits rows. Nearly everything uses LIMIT; the
    #: exceptions are the reason this field exists.
    limit_style: str = "limit"  # "limit" | "top" | "fetch_first" | "rownum"
    #: Extra settings beyond the shape's usual ones.
    extra_fields: tuple[ConfigField, ...] = ()
    tier: Tier = Tier.SPEC_ONLY
    #: What backs a tier above 4.
    verified_by: str | None = None
    #: True when the dialect is bundled with SQLAlchemy itself.
    builtin: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.tier is not Tier.SPEC_ONLY and not self.verified_by:
            raise ValueError(
                f"{self.key} claims tier {int(self.tier)} without saying what verified it."
            )
        if self.limit_style not in ("limit", "top", "fetch_first", "rownum"):
            raise ValueError(f"{self.key}: unknown limit style '{self.limit_style}'.")

    def sample_sql(self, table: str, rows: int) -> str:
        """A statement that reads a few rows, in this dialect's spelling.

        Not for correctness -- SQLAlchemy builds real queries -- but for the
        preview the UI shows and for the connection test, which both need a
        cheap statement that works everywhere.
        """
        if self.limit_style == "top":
            return f"SELECT TOP {rows} * FROM {table}"
        if self.limit_style == "fetch_first":
            return f"SELECT * FROM {table} FETCH FIRST {rows} ROWS ONLY"
        if self.limit_style == "rownum":
            return f"SELECT * FROM {table} WHERE ROWNUM <= {rows}"
        return f"SELECT * FROM {table} LIMIT {rows}"

    def config_fields(self) -> tuple[ConfigField, ...]:
        if self.shape == FILE:
            base: tuple[ConfigField, ...] = (
                ConfigField(
                    "file_path",
                    "File path",
                    placeholder="/data/warehouse.db",
                    help="An absolute path on the machine running the platform.",
                ),
            )
        elif self.shape == ACCOUNT:
            base = (
                ConfigField("account", "Account", placeholder="ab12345.eu-west-1"),
                ConfigField("database", "Database"),
                ConfigField("username", "Username"),
                ConfigField("password", "Password", kind="secret"),
            )
        else:
            base = (
                ConfigField("host", "Host", placeholder="db.internal"),
                ConfigField(
                    "port", "Port", kind="number", required=False, default=self.default_port
                ),
                ConfigField("database", "Database"),
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
        return base + self.extra_fields

    def available(self) -> tuple[bool, str | None]:
        """Whether the driver is installed here.

        Imported rather than assumed: a spec that promises `read` on a database
        whose driver is missing is a promise the caller only discovers by
        trying, which is exactly what declared capabilities exist to prevent.
        """
        if self.builtin:
            return True, None
        root = self.package.replace("-", "_").split("[")[0]
        for candidate in (root, self.driver.split("+")[-1]):
            if importlib.util.find_spec(candidate) is not None:
                return True, None
        return False, (
            f"{self.label} needs the '{self.package}' package, which is not installed "
            "on this deployment."
        )

    def to_spec(self) -> ConnectorSpec:
        available, reason = self.available()
        capabilities = (
            {"test", "discover", "schema", "read", "incremental"} if available else {"test"}
        )
        return ConnectorSpec(
            type=self.key,
            label=self.label,
            category=self.category,
            description=self.description or f"Read tables from {self.label}.",
            config_fields=self.config_fields(),
            capabilities=frozenset(capabilities),
            driver_package=None if self.builtin else self.package,
            documentation_url=self.docs_url,
            available=available,
            unavailable_reason=reason,
            tier=self.tier,
            verified_by=self.verified_by,
            origin="dialect",
        )


@dataclass
class DialectTable:
    entries: dict[str, Dialect] = field(default_factory=dict)

    def add(self, dialect: Dialect) -> Dialect:
        if dialect.key in self.entries:
            raise ValueError(f"'{dialect.key}' is already in the dialect table.")
        self.entries[dialect.key] = dialect
        return dialect

    def get(self, key: str) -> Dialect | None:
        return self.entries.get(key)

    def all(self) -> list[Dialect]:
        return sorted(self.entries.values(), key=lambda entry: entry.label.lower())


TABLE = DialectTable()


def _d(**kwargs: Any) -> Dialect:
    return TABLE.add(Dialect(**kwargs))


# ---------------------------------------------------------------- relational
#
# The three at the top share their keys with hand-written adapters, and are
# therefore *shadowed*: the generator skips them and the tested connector wins.
# They stay in the table because the table is also the reference for how each
# database is reached, and a gap where PostgreSQL should be would read as an
# absence rather than as a deliberate hand-off.

_d(key="postgresql", label="PostgreSQL", driver="postgresql+psycopg", package="psycopg[binary]",
   default_port=5432, tier=Tier.CONTAINER, verified_by="test_containers.py",
   description="Read tables from PostgreSQL.", docs_url="https://www.postgresql.org/docs/")
_d(key="mysql", label="MySQL", driver="mysql+pymysql", package="pymysql", default_port=3306,
   tier=Tier.CONTAINER, verified_by="test_containers.py",
   description="Read tables from MySQL.", docs_url="https://dev.mysql.com/doc/")
_d(key="sqlite", label="SQLite", driver="sqlite", package="", shape=FILE, builtin=True,
   description="Read tables from a SQLite file.")

_d(key="mariadb", label="MariaDB", driver="mysql+pymysql", package="pymysql", default_port=3306,
   tier=Tier.CONTAINER, verified_by="test_containers.py",
   description="Read tables from MariaDB, over the MySQL protocol.")
_d(key="sqlserver", label="Microsoft SQL Server", driver="mssql+pyodbc", package="pyodbc",
   default_port=1433, limit_style="top", description="Read tables from SQL Server.")
_d(key="oracle_db", label="Oracle Database", driver="oracle+oracledb", package="oracledb",
   default_port=1521, limit_style="fetch_first", description="Read tables from Oracle.")
_d(key="db2", label="IBM Db2", driver="ibm_db_sa", package="ibm-db-sa", default_port=50000,
   limit_style="fetch_first", description="Read tables from IBM Db2.")
_d(key="hana", label="SAP HANA", driver="hana", package="sqlalchemy-hana", default_port=30015,
   limit_style="limit", description="Read tables from SAP HANA.")
_d(key="sybase", label="Sybase ASE", driver="sybase+pyodbc", package="pyodbc", default_port=5000,
   limit_style="top", description="Read tables from Sybase ASE.")
_d(key="firebird", label="Firebird", driver="firebird+fdb", package="fdb", default_port=3050,
   limit_style="fetch_first", description="Read tables from Firebird.")
_d(key="informix", label="IBM Informix", driver="informix", package="ibm-db-sa", default_port=9088,
   limit_style="fetch_first", description="Read tables from Informix.")
_d(key="cockroachdb", label="CockroachDB", driver="cockroachdb+psycopg", package="sqlalchemy-cockroachdb",
   default_port=26257, description="Read tables from CockroachDB, over the Postgres wire protocol.")
_d(key="yugabytedb", label="YugabyteDB", driver="postgresql+psycopg", package="psycopg[binary]",
   default_port=5433, description="Read tables from YugabyteDB, over the Postgres wire protocol.")
_d(key="tidb", label="TiDB", driver="mysql+pymysql", package="pymysql", default_port=4000,
   description="Read tables from TiDB, over the MySQL wire protocol.")
_d(key="aurora_postgres", label="Amazon Aurora (PostgreSQL)", driver="postgresql+psycopg",
   package="psycopg[binary]", default_port=5432, description="Read tables from Aurora's PostgreSQL engine.")
_d(key="aurora_mysql", label="Amazon Aurora (MySQL)", driver="mysql+pymysql", package="pymysql",
   default_port=3306, description="Read tables from Aurora's MySQL engine.")
_d(key="cloud_sql", label="Google Cloud SQL", driver="postgresql+psycopg", package="psycopg[binary]",
   default_port=5432, description="Read tables from Cloud SQL. Choose the engine your instance runs.")
_d(key="azure_sql", label="Azure SQL Database", driver="mssql+pyodbc", package="pyodbc",
   default_port=1433, limit_style="top", description="Read tables from Azure SQL Database.")
_d(key="planetscale", label="PlanetScale", driver="mysql+pymysql", package="pymysql", default_port=3306,
   description="Read tables from PlanetScale, over the MySQL wire protocol.")
_d(key="neon", label="Neon", driver="postgresql+psycopg", package="psycopg[binary]", default_port=5432,
   description="Read tables from Neon, over the Postgres wire protocol.")
_d(key="supabase_db", label="Supabase (Postgres)", driver="postgresql+psycopg", package="psycopg[binary]",
   default_port=5432, description="Read tables from a Supabase project's Postgres database.")
_d(key="duckdb", label="DuckDB", driver="duckdb", package="duckdb-engine", shape=FILE,
   description="Read tables from a DuckDB file.")
_d(key="clickhouse", label="ClickHouse", driver="clickhouse+native", package="clickhouse-sqlalchemy",
   default_port=9000, description="Read tables from ClickHouse.")
_d(key="vertica", label="Vertica", driver="vertica+vertica_python", package="vertica-python",
   default_port=5433, description="Read tables from Vertica.")
_d(key="greenplum", label="Greenplum", driver="postgresql+psycopg", package="psycopg[binary]",
   default_port=5432, description="Read tables from Greenplum, over the Postgres wire protocol.")
_d(key="teradata", label="Teradata", driver="teradatasql", package="teradatasqlalchemy",
   default_port=1025, limit_style="top", description="Read tables from Teradata.")
_d(key="exasol", label="Exasol", driver="exa+pyodbc", package="sqlalchemy-exasol", default_port=8563,
   description="Read tables from Exasol.")
_d(key="monetdb", label="MonetDB", driver="monetdb", package="sqlalchemy-monetdb", default_port=50000,
   description="Read tables from MonetDB.")
_d(key="netezza", label="IBM Netezza", driver="netezza+nzpy", package="nzalchemy", default_port=5480,
   limit_style="limit", description="Read tables from Netezza.")
_d(key="singlestore", label="SingleStore", driver="mysql+pymysql", package="pymysql", default_port=3306,
   description="Read tables from SingleStore, over the MySQL wire protocol.")
_d(key="starrocks", label="StarRocks", driver="mysql+pymysql", package="pymysql", default_port=9030,
   description="Read tables from StarRocks, over the MySQL wire protocol.")
_d(key="apache_doris", label="Apache Doris", driver="mysql+pymysql", package="pymysql", default_port=9030,
   description="Read tables from Apache Doris, over the MySQL wire protocol.")
_d(key="trino", label="Trino", driver="trino", package="trino", default_port=8080,
   description="Query anything Trino federates, as one database.")
_d(key="presto", label="Presto", driver="presto", package="pyhive", default_port=8080,
   description="Query anything Presto federates, as one database.")

# ---------------------------------------------------- warehouses & lakehouses

_d(key="snowflake", label="Snowflake", driver="snowflake", package="snowflake-sqlalchemy",
   category="warehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("warehouse", "Warehouse"), ConfigField("role", "Role", required=False)),
   description="Read from a Snowflake warehouse.", docs_url="https://docs.snowflake.com/")
_d(key="bigquery", label="Google BigQuery", driver="bigquery", package="sqlalchemy-bigquery",
   category="warehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("credentials_json", "Service account JSON", kind="secret"),),
   description="Read from BigQuery.", docs_url="https://cloud.google.com/bigquery/docs")
_d(key="redshift", label="Amazon Redshift", driver="redshift+psycopg2", package="sqlalchemy-redshift",
   category="warehouse", default_port=5439, description="Read from a Redshift cluster.")
_d(key="databricks_sql", label="Databricks SQL", driver="databricks", package="databricks-sqlalchemy",
   category="warehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("http_path", "HTTP path", placeholder="/sql/1.0/warehouses/abc"),),
   description="Read from a Databricks SQL warehouse.")
_d(key="synapse", label="Azure Synapse", driver="mssql+pyodbc", package="pyodbc",
   category="warehouse", default_port=1433, limit_style="top",
   description="Read from Azure Synapse Analytics.")
_d(key="athena", label="Amazon Athena", driver="awsathena+rest", package="pyathena",
   category="warehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("s3_staging_dir", "S3 staging directory", placeholder="s3://bucket/athena/"),),
   description="Query data in S3 through Athena.")
_d(key="dremio", label="Dremio", driver="dremio+flight", package="sqlalchemy-dremio",
   category="warehouse", default_port=32010, description="Read from Dremio.")
_d(key="firebolt", label="Firebolt", driver="firebolt", package="firebolt-sqlalchemy",
   category="warehouse", shape=ACCOUNT, description="Read from Firebolt.")
_d(key="motherduck", label="MotherDuck", driver="duckdb", package="duckdb-engine",
   category="warehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("motherduck_token", "Token", kind="secret"),),
   description="Read from MotherDuck, DuckDB in the cloud.")
_d(key="rockset", label="Rockset", driver="rockset", package="rockset-sqlalchemy",
   category="warehouse", shape=ACCOUNT, description="Read from Rockset.")
_d(key="hive", label="Apache Hive", driver="hive", package="pyhive", category="warehouse",
   default_port=10000, description="Read tables from Hive.")
_d(key="impala", label="Apache Impala", driver="impala", package="impyla", category="warehouse",
   default_port=21050, description="Read tables from Impala.")

# ------------------------------------------------ table formats & catalogues
#
# Read through an engine that understands them, which is what a person querying
# a lakehouse actually does. The alternative -- reimplementing the table format
# here -- is a project, not a connector.

_d(key="delta_lake", label="Delta Lake", driver="databricks", package="databricks-sqlalchemy",
   category="lakehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("http_path", "HTTP path"),),
   description="Read Delta tables through a Databricks SQL warehouse.")
_d(key="iceberg", label="Apache Iceberg", driver="trino", package="trino", category="lakehouse",
   default_port=8080, extra_fields=(ConfigField("catalog", "Catalog", default="iceberg"),),
   description="Read Iceberg tables through a Trino catalogue.")
_d(key="hudi", label="Apache Hudi", driver="hive", package="pyhive", category="lakehouse",
   default_port=10000, description="Read Hudi tables through Hive.")
_d(key="hive_metastore", label="Hive Metastore", driver="hive", package="pyhive",
   category="lakehouse", default_port=9083, description="Read tables catalogued in a Hive Metastore.")
_d(key="glue_catalog", label="AWS Glue Catalog", driver="awsathena+rest", package="pyathena",
   category="lakehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("s3_staging_dir", "S3 staging directory"),),
   description="Read tables catalogued in Glue, through Athena.")
_d(key="unity_catalog", label="Unity Catalog", driver="databricks", package="databricks-sqlalchemy",
   category="lakehouse", shape=ACCOUNT,
   extra_fields=(ConfigField("http_path", "HTTP path"), ConfigField("catalog", "Catalog")),
   description="Read tables governed by Unity Catalog.")

# ------------------------------------------------------------- time series

_d(key="timescaledb", label="TimescaleDB", driver="postgresql+psycopg", package="psycopg[binary]",
   category="timeseries", default_port=5432,
   description="Read hypertables from TimescaleDB, over the Postgres wire protocol.")
_d(key="questdb", label="QuestDB", driver="postgresql+psycopg", package="psycopg[binary]",
   category="timeseries", default_port=8812,
   description="Read from QuestDB, over the Postgres wire protocol.")
_d(key="crate", label="CrateDB", driver="crate", package="crate", category="timeseries",
   default_port=4200, description="Read from CrateDB.")


def all_dialects() -> list[Dialect]:
    return TABLE.all()


def dialect_for(key: str) -> Dialect | None:
    return TABLE.get(key)
