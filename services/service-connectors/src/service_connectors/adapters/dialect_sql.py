"""One connector for every entry in the dialect table.

SQLAlchemy already knows how to introspect and read from each of these; what
differs between them is the URL, the driver package, and the spelling of "give
me a few rows". Those live in `dialects.py`, so this file is the same code for
all of them.

Where the driver is missing, the connector still exists and still answers
`test()` -- with the name of the package to install. That is deliberate: a
catalogue that hides what the platform is designed to reach is less useful than
one that says "this needs `pyodbc`", and a spec whose capabilities narrowed to
`test` cannot promise a read it would fail to deliver.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from service_connectors.dialects import ACCOUNT, FILE, Dialect
from service_connectors.protocol import (
    ConnectorError,
    ConnectorSpec,
    ReadResult,
    StreamColumn,
    StreamRef,
    TestResult,
    with_tier_note,
)

#: A connection that has not answered by now is not going to.
CONNECT_TIMEOUT_SECONDS = 10

#: Schemas that belong to the database rather than to anybody's data.
_SYSTEM_SCHEMAS = frozenset(
    {
        "information_schema", "pg_catalog", "pg_toast", "sys", "mysql",
        "performance_schema", "sysaux", "system", "INFORMATION_SCHEMA",
    }
)


class DialectConnector:
    """A SQL database, driven from a `Dialect` entry."""

    def __init__(self, dialect: Dialect) -> None:
        self.dialect = dialect
        self.spec: ConnectorSpec = dialect.to_spec()

    # ------------------------------------------------------------------ url

    def _url(self, config: dict[str, Any]) -> URL:
        dialect = self.dialect
        if dialect.shape == FILE:
            path = str(config.get("file_path") or "").strip()
            if not path:
                raise ConnectorError(f"{dialect.label} needs a file path.")
            return URL.create(dialect.driver, database=path)

        if dialect.shape == ACCOUNT:
            account = str(config.get("account") or "").strip()
            if not account:
                raise ConnectorError(f"{dialect.label} needs an account.")
            return URL.create(
                dialect.driver,
                username=str(config.get("username") or "") or None,
                password=str(config.get("password") or "") or None,
                host=account,
                database=str(config.get("database") or "") or None,
                query={
                    key: str(value)
                    for key, value in config.items()
                    if key in {"warehouse", "role", "http_path", "catalog", "s3_staging_dir"}
                    and value
                },
            )

        host = str(config.get("host") or "").strip()
        if not host:
            raise ConnectorError(f"{dialect.label} needs a host.")
        return URL.create(
            dialect.driver,
            username=str(config.get("username") or "") or None,
            password=str(config.get("password") or "") or None,
            host=host,
            port=int(config["port"]) if config.get("port") else dialect.default_port,
            database=str(config.get("database") or "") or None,
        )

    def _engine(self, config: dict[str, Any]):
        if not self.spec.available:
            raise ConnectorError(self.spec.unavailable_reason or f"{self.dialect.label} is unavailable.")
        try:
            return create_engine(self._url(config), pool_pre_ping=True)
        except SQLAlchemyError as exc:
            raise ConnectorError(f"{self.dialect.label} could not be reached: {exc}") from exc

    # --------------------------------------------------------------- surface

    def test(self, config: dict[str, Any]) -> TestResult:
        if not self.spec.available:
            # The whole point of keeping an unavailable connector in the
            # catalogue: it says what to install rather than disappearing.
            return TestResult(
                success=False,
                message=self.spec.unavailable_reason
                or f"{self.dialect.label} is not available on this deployment.",
            )

        started = time.perf_counter()
        engine = None
        try:
            engine = self._engine(config)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                version = self._server_version(connection)
        except ConnectorError as exc:
            return TestResult(success=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001 - a driver error is the answer here
            return TestResult(success=False, message=_safe(exc))
        finally:
            if engine is not None:
                engine.dispose()

        return with_tier_note(
            TestResult(
                success=True,
                message=f"Connected to {self.dialect.label}.",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                server_version=version,
            ),
            self.spec,
        )

    def discover(self, config: dict[str, Any]) -> list[StreamRef]:
        engine = self._engine(config)
        try:
            inspector = inspect(engine)
            found: list[StreamRef] = []
            for schema in self._schemas(inspector):
                for name in inspector.get_table_names(schema=schema):
                    found.append(StreamRef(name=name, namespace=schema, kind="table"))
                for name in inspector.get_view_names(schema=schema):
                    found.append(StreamRef(name=name, namespace=schema, kind="view"))
            return found
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Could not list what is in {self.dialect.label}: {_safe(exc)}") from exc
        finally:
            engine.dispose()

    def columns(self, config: dict[str, Any], stream: StreamRef) -> list[StreamColumn]:
        engine = self._engine(config)
        try:
            inspector = inspect(engine)
            primary = set(
                (inspector.get_pk_constraint(stream.name, schema=stream.namespace) or {}).get(
                    "constrained_columns"
                )
                or []
            )
            return [
                StreamColumn(
                    name=str(column["name"]),
                    data_type=str(column.get("type", "")),
                    nullable=bool(column.get("nullable", True)),
                    primary_key=str(column["name"]) in primary,
                )
                for column in inspector.get_columns(stream.name, schema=stream.namespace)
            ]
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                f"Could not read the columns of {stream.qualified_name}: {_safe(exc)}"
            ) from exc
        finally:
            engine.dispose()

    def read(
        self,
        config: dict[str, Any],
        stream: StreamRef,
        *,
        limit: int = 10_000,
        cursor: str | None = None,
    ) -> ReadResult:
        import pandas as pd

        engine = self._engine(config)
        try:
            quote = engine.dialect.identifier_preparer.quote
            qualified = (
                f"{quote(stream.namespace)}.{quote(stream.name)}"
                if stream.namespace
                else quote(stream.name)
            )
            # One more than asked for, so "there is more" is a fact rather than
            # a guess from a full page.
            statement = self.dialect.sample_sql(qualified, limit + 1)
            with engine.connect() as connection:
                frame = pd.read_sql_query(text(statement), connection)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                f"Could not read {stream.qualified_name}: {_safe(exc)}"
            ) from exc
        finally:
            engine.dispose()

        truncated = len(frame) > limit
        if truncated:
            frame = frame.head(limit)
        return with_tier_note(
            ReadResult(dataframe=frame, row_count=len(frame), truncated=truncated),
            self.spec,
        )

    # --------------------------------------------------------------- private

    def _schemas(self, inspector: Any) -> list[str | None]:
        try:
            names = [
                name for name in inspector.get_schema_names() if name not in _SYSTEM_SCHEMAS
            ]
        except Exception:  # noqa: BLE001 - a dialect without schema listing is fine
            return [None]
        return names or [None]

    def _server_version(self, connection: Any) -> str | None:
        raw = getattr(getattr(connection, "connection", None), "server_version", None)
        if raw:
            return str(raw)
        try:
            info = connection.engine.dialect.server_version_info
        except Exception:  # noqa: BLE001
            return None
        return ".".join(str(part) for part in info) if info else None


def _safe(exc: Exception) -> str:
    """A driver's complaint, without the connection string it was holding."""
    message = str(getattr(exc, "orig", None) or exc)
    for marker in ("\n[SQL:", "\n(Background on this error"):
        head, sep, _ = message.partition(marker)
        if sep:
            message = head
    # A URL in an error message is a password in a log.
    import re

    message = re.sub(r"\b\w+://[^\s]+", "<connection>", message)
    return message.strip()[:500] or "The database refused the connection."
