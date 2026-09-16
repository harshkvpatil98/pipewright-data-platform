"""Connectors driven against a real database server in a container.

SQLite is exercised elsewhere and proves a great deal, but it is a file. The
things that only go wrong against a *server* -- a wire protocol, a login, a
`search_path`, an information schema that is not SQLite's, a server version
string -- need a server, and the roadmap's tier 2 is the word for "a container
in CI runs this on every merge".

**How it is wired.** `.github/workflows/ci.yml` starts PostgreSQL and MySQL as
service containers and exports the two URLs below. Locally, `docker compose up
-d postgres` supplies the PostgreSQL one at its default address; anything not
reachable is skipped with a reason rather than failing, because a developer
without a MySQL server should not have a red suite.

**What is deliberately not promoted by this file.** Nine dialect entries --
CockroachDB, YugabyteDB, Greenplum, Neon, Supabase, Cloud SQL, Aurora
PostgreSQL, TimescaleDB, QuestDB -- drive `postgresql+psycopg`, so every one of
them executes the code path this file exercises. None of them is promoted by
it. "CockroachDB works" and "the PostgreSQL driver works" are different claims,
and a tier system that quietly conflates them is worth nothing. Each stays at
tier 4 until something runs a CockroachDB.
"""

from __future__ import annotations

import os
import uuid
import pathlib
from collections.abc import Iterator

import pytest
import sqlalchemy as sa

import service_connectors  # noqa: F401  -- assembles the catalogue
from service_connectors.adapters.dialect_sql import DialectConnector
from service_connectors.dialects import all_dialects
from service_connectors.protocol import ConnectorError, StreamRef
from service_connectors.registry import get

#: What this file is cited as by the connectors it verifies.
CITATION = "test_containers.py"

#: The compose defaults, so a developer who has run `docker compose up -d
#: postgres` gets this suite without configuring anything.
DEFAULT_POSTGRES = "postgresql+psycopg://platform:platform@127.0.0.1:5432/platform"
DEFAULT_MYSQL = "mysql+pymysql://root:platform@127.0.0.1:3306/platform"

SERVERS = {
    "postgresql": ("CONNECTORS_TEST_POSTGRES_URL", DEFAULT_POSTGRES),
    "mysql": ("CONNECTORS_TEST_MYSQL_URL", DEFAULT_MYSQL),
}


def _url(key: str) -> str:
    variable, default = SERVERS[key]
    return os.environ.get(variable, default)


def _reachable(url: str) -> bool:
    try:
        engine = sa.create_engine(url, pool_pre_ping=False, connect_args={"connect_timeout": 3})
    except Exception:  # noqa: BLE001 - a missing driver is "not reachable"
        return False
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        engine.dispose()


def _require(key: str) -> str:
    url = _url(key)
    if not _reachable(url):
        variable, _ = SERVERS[key]
        pytest.skip(
            f"No {key} server at the configured address. Start one "
            f"(`docker compose up -d postgres` for PostgreSQL) or set {variable}."
        )
    return url


def _config_from(url: str) -> dict[str, object]:
    """The connector settings a person would fill in, from a SQLAlchemy URL."""
    parsed = sa.engine.make_url(url)
    config: dict[str, object] = {
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "password": parsed.password,
    }
    if parsed.get_backend_name() == "postgresql":
        # The compose container has no TLS, and `require` would refuse it. A
        # developer against a managed server would leave the default alone.
        config["sslmode"] = "disable"
    return config


@pytest.fixture(scope="module")
def postgres() -> Iterator[tuple[str, str]]:
    """A schema with a table and a view in it, dropped afterwards."""
    url = _require("postgresql")
    schema = f"probe_{uuid.uuid4().hex[:8]}"
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            sa.text(
                f'CREATE TABLE "{schema}".orders ('
                "id integer PRIMARY KEY, region text NOT NULL, total numeric(10,2))"
            )
        )
        connection.execute(
            sa.text(
                f"INSERT INTO \"{schema}\".orders VALUES "
                "(1,'eu',10.50),(2,'us',20.00),(3,'eu',30.25)"
            )
        )
        connection.execute(
            sa.text(
                f'CREATE VIEW "{schema}".eu_orders AS '
                f"SELECT * FROM \"{schema}\".orders WHERE region='eu'"
            )
        )
    try:
        yield url, schema
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture(scope="module")
def mysql() -> Iterator[tuple[str, str]]:
    """MySQL has no schema separate from the database, so the database is it."""
    url = _require("mysql")
    engine = sa.create_engine(url)
    table = f"probe_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE TABLE `{table}` ("
                "id INT PRIMARY KEY, region VARCHAR(8) NOT NULL, total DECIMAL(10,2))"
            )
        )
        connection.execute(
            sa.text(
                f"INSERT INTO `{table}` VALUES (1,'eu',10.50),(2,'us',20.00),(3,'eu',30.25)"
            )
        )
    try:
        yield url, table
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text(f"DROP TABLE IF EXISTS `{table}`"))
        engine.dispose()


def _dialect(key: str) -> DialectConnector:
    return DialectConnector(next(entry for entry in all_dialects() if entry.key == key))


class TestPostgresThroughTheDialectTable:
    def test_it_connects_and_reports_the_server_version(self, postgres) -> None:
        url, _ = postgres
        result = _dialect("postgresql").test(_config_from(url))
        assert result.success, result.message
        assert result.server_version, "a real server should say what it is"
        assert result.latency_ms is not None

    def test_it_finds_the_table_and_the_view(self, postgres) -> None:
        url, schema = postgres
        streams = _dialect("postgresql").discover(_config_from(url))
        found = {
            stream.name: stream.kind for stream in streams if stream.namespace == schema
        }
        assert found == {"orders": "table", "eu_orders": "view"}

    def test_it_reads_columns_with_the_key_and_nullability_marked(self, postgres) -> None:
        url, schema = postgres
        connector = _dialect("postgresql")
        columns = connector.columns(
            _config_from(url), StreamRef(name="orders", namespace=schema)
        )
        by_name = {column.name: column for column in columns}
        assert by_name["id"].primary_key
        assert not by_name["region"].nullable
        assert by_name["total"].nullable

    def test_it_reads_rows(self, postgres) -> None:
        url, schema = postgres
        result = _dialect("postgresql").read(
            _config_from(url), StreamRef(name="orders", namespace=schema), limit=10
        )
        assert result.row_count == 3
        assert not result.truncated
        assert sorted(result.dataframe["region"]) == ["eu", "eu", "us"]

    def test_a_limit_reports_that_it_truncated(self, postgres) -> None:
        url, schema = postgres
        result = _dialect("postgresql").read(
            _config_from(url), StreamRef(name="orders", namespace=schema), limit=2
        )
        assert result.row_count == 2
        assert result.truncated

    def test_a_quoted_identifier_survives_the_round_trip(self, postgres) -> None:
        """The schema name is generated, so this is not a fixed-string test."""
        url, schema = postgres
        result = _dialect("postgresql").read(
            _config_from(url), StreamRef(name="eu_orders", namespace=schema), limit=10
        )
        assert result.row_count == 2

    def test_a_missing_table_is_an_actionable_error(self, postgres) -> None:
        url, schema = postgres
        with pytest.raises(ConnectorError, match="Could not read"):
            _dialect("postgresql").read(
                _config_from(url), StreamRef(name="ghost", namespace=schema), limit=1
            )

    def test_a_bad_password_never_leaks_the_connection_string(self, postgres) -> None:
        """A URL in an error message is a password in a log."""
        url, _ = postgres
        result = _dialect("postgresql").test({**_config_from(url), "password": "wrong"})
        assert not result.success
        assert "postgresql://" not in result.message
        assert "wrong" not in result.message

    def test_a_verified_connection_carries_no_tier_caveat(self, postgres) -> None:
        url, _ = postgres
        result = _dialect("postgresql").test(_config_from(url))
        assert not any("unverified" in warning.lower() for warning in result.warnings)


class TestPostgresThroughTheHandwrittenConnector:
    """The SDK connector the extraction service actually drives.

    Separate from the dialect table on purpose: these are two code paths to the
    same database, and the one extraction uses is the one whose tier matters to
    a run.
    """

    def test_it_connects(self, postgres) -> None:
        url, _ = postgres
        result = get("postgresql").test(_config_from(url))
        assert result.success, result.message

    def test_it_discovers_and_reads(self, postgres) -> None:
        url, schema = postgres
        connector = get("postgresql")
        # The schema setting exists precisely so a connection is not confined
        # to `public`; this is the test that would have caught its absence.
        config = {**_config_from(url), "schema": schema}
        stream = next(
            item
            for item in connector.discover(config)
            if item.name == "orders" and item.namespace == schema
        )
        result = connector.read(config, stream, limit=10)
        assert result.row_count == 3

    def test_the_columns_describe_the_table(self, postgres) -> None:
        url, schema = postgres
        connector = get("postgresql")
        columns = connector.columns(
            _config_from(url), StreamRef(name="orders", namespace=schema)
        )
        assert {column.name for column in columns} == {"id", "region", "total"}


class TestMysqlThroughTheDialectTable:
    def test_it_connects_and_reports_the_server_version(self, mysql) -> None:
        url, _ = mysql
        result = _dialect("mysql").test(_config_from(url))
        assert result.success, result.message
        assert result.server_version

    def test_it_finds_the_table(self, mysql) -> None:
        url, table = mysql
        streams = _dialect("mysql").discover(_config_from(url))
        assert table in {stream.name for stream in streams}

    def test_it_reads_rows(self, mysql) -> None:
        url, table = mysql
        result = _dialect("mysql").read(_config_from(url), StreamRef(name=table), limit=10)
        assert result.row_count == 3
        assert sorted(result.dataframe["region"]) == ["eu", "eu", "us"]

    def test_a_limit_reports_that_it_truncated(self, mysql) -> None:
        url, table = mysql
        result = _dialect("mysql").read(_config_from(url), StreamRef(name=table), limit=2)
        assert result.row_count == 2
        assert result.truncated

    def test_a_bad_password_never_leaks_the_connection_string(self, mysql) -> None:
        url, _ = mysql
        result = _dialect("mysql").test({**_config_from(url), "password": "wrong"})
        assert not result.success
        assert "mysql+pymysql" not in result.message


class TestMariadbUsesTheSameDriver:
    """MariaDB is its own entry in the table and its own tier.

    It is verified against a MariaDB image when CI provides one, and skipped
    otherwise. Pointing it at a MySQL server and calling the result "MariaDB
    tested" is the kind of shortcut the tier system exists to refuse.
    """

    def test_it_connects(self) -> None:
        url = os.environ.get("CONNECTORS_TEST_MARIADB_URL")
        if not url or not _reachable(url):
            pytest.skip("no MariaDB server; set CONNECTORS_TEST_MARIADB_URL")
        result = _dialect("mariadb").test(_config_from(url))
        assert result.success, result.message


class TestTheClaimsThisFileBacks:
    """Whatever cites this file has to be exercised by it.

    A citation nothing runs is the tier system's own failure mode: the badge
    says "Tested", the audit says "backed by test_containers.py", and nothing
    in test_containers.py ever mentions the connector.
    """

    def test_every_citation_is_named_in_this_module(self) -> None:
        from service_connectors.registry import specs

        body = pathlib.Path(__file__).read_text(encoding="utf-8")
        citing = sorted(spec.type for spec in specs() if spec.verified_by == CITATION)
        uncovered = [key for key in citing if f'"{key}"' not in body]
        assert uncovered == [], (
            f"these connectors cite {CITATION} but nothing here exercises them: {uncovered}"
        )

    def test_a_postgres_wire_dialect_is_not_quietly_promoted(self) -> None:
        """The distinction this file is careful about, pinned as a test."""
        from service_connectors.registry import spec_for

        for key in (
            "cockroachdb", "yugabytedb", "greenplum", "neon", "supabase_db",
            "cloud_sql", "aurora_postgres", "timescaledb", "questdb",
        ):
            assert spec_for(key).verified_by != CITATION, (
                f"{key} drives the PostgreSQL driver, which is not the same claim "
                "as {key} having been run"
            )
