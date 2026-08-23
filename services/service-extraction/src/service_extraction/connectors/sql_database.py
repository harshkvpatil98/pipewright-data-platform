"""SQL database connector for PostgreSQL, MySQL, and SQLite.

All three speak through SQLAlchemy so discovery, preview, and extraction share
one code path. Engines are cached per connection so repeated operations reuse a
warm pool instead of paying TCP + TLS + auth on every request.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import pandas as pd
from sqlalchemy import URL, Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from service_extraction.connectors.base import (
    SUPPORTED_CONNECTOR_TYPES,
    ConnectionTestResult,
    DiscoveredColumn,
    ExtractionResult,
    TableRef,
)
from service_extraction.sql_safety import ensure_read_only_select
from shared_python.errors import BadRequestError
from shared_python.logging import get_logger

logger = get_logger(__name__)

_DRIVERS = {
    "postgresql": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
    "sqlite": "sqlite",
}

_DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306}

# Engines hold pooled sockets, so the cache is bounded and evicts least-recently used.
_ENGINE_CACHE: OrderedDict[str, Engine] = OrderedDict()
_ENGINE_CACHE_LOCK = threading.Lock()
_ENGINE_CACHE_MAX = 16

CONNECT_TIMEOUT_SECONDS = 8
DEFAULT_PREVIEW_LIMIT = 50
DEFAULT_MAX_ROWS = 1_000_000
DEFAULT_CHUNK_SIZE = 50_000


def _require(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError(f"Connection configuration is missing '{key}'.")
    return value.strip()


def build_url(connector_type: str, config: dict[str, Any]) -> URL:
    """Translate a stored connection config into a SQLAlchemy URL."""
    if connector_type not in SUPPORTED_CONNECTOR_TYPES:
        raise BadRequestError(
            f"Unsupported connector type '{connector_type}'. "
            f"Supported types: {', '.join(SUPPORTED_CONNECTOR_TYPES)}."
        )

    if connector_type == "sqlite":
        # SQLite is file-backed; there is no host/user/password to resolve.
        file_path = _require(config, "file_path")

        # SQLite happily creates a database when the file is absent, which turns
        # a mistyped path into an empty database and a baffling "no such table"
        # later. Fail here instead, where the cause is obvious.
        if not os.path.isabs(file_path):
            raise BadRequestError(
                f"SQLite path '{file_path}' must be absolute; a relative path is "
                "resolved against the server's working directory, not yours."
            )
        if not os.path.isfile(file_path):
            raise BadRequestError(f"No SQLite database exists at '{file_path}'.")

        return URL.create("sqlite", database=file_path)

    raw_port = config.get("port") or _DEFAULT_PORTS[connector_type]
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise BadRequestError("Connection port must be a number.") from exc
    if not 1 <= port <= 65535:
        raise BadRequestError("Connection port must be between 1 and 65535.")

    return URL.create(
        _DRIVERS[connector_type],
        username=_require(config, "username"),
        password=config.get("password") or None,
        host=_require(config, "host"),
        port=port,
        database=_require(config, "database"),
    )


def _connect_args(connector_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if connector_type == "sqlite":
        return {"timeout": CONNECT_TIMEOUT_SECONDS}
    if connector_type == "postgresql":
        args: dict[str, Any] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
        ssl_mode = config.get("ssl_mode")
        if isinstance(ssl_mode, str) and ssl_mode:
            args["sslmode"] = ssl_mode
        return args
    # MySQL
    args = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    if config.get("ssl_mode") in {"require", "verify-ca", "verify-full"}:
        args["ssl"] = {"ssl_mode": "REQUIRED"}
    return args


def _cache_key(url: URL, connector_type: str) -> str:
    # render_as_string(hide_password=False) includes the secret, so the key is hashed
    # rather than stored; it is never logged.
    raw = f"{connector_type}|{url.render_as_string(hide_password=False)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_engine(connector_type: str, config: dict[str, Any]) -> Engine:
    """Return a pooled engine for this connection, creating it on first use."""
    url = build_url(connector_type, config)
    key = _cache_key(url, connector_type)

    with _ENGINE_CACHE_LOCK:
        cached = _ENGINE_CACHE.get(key)
        if cached is not None:
            _ENGINE_CACHE.move_to_end(key)
            return cached

        pool_kwargs: dict[str, Any] = {}
        if connector_type != "sqlite":
            pool_kwargs = {
                "pool_size": 5,
                "max_overflow": 5,
                "pool_recycle": 1800,
                "pool_timeout": 10,
            }

        engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args=_connect_args(connector_type, config),
            **pool_kwargs,
        )

        _ENGINE_CACHE[key] = engine
        _ENGINE_CACHE.move_to_end(key)
        while len(_ENGINE_CACHE) > _ENGINE_CACHE_MAX:
            _, evicted = _ENGINE_CACHE.popitem(last=False)
            evicted.dispose()
        return engine


def dispose_cached_engines() -> None:
    """Close every pooled engine. Used on shutdown and by tests."""
    with _ENGINE_CACHE_LOCK:
        for engine in _ENGINE_CACHE.values():
            engine.dispose()
        _ENGINE_CACHE.clear()


def _safe_error(exc: Exception) -> str:
    """First line of a driver error, truncated, so credentials never leak out."""
    return str(exc).splitlines()[0][:400] if str(exc) else exc.__class__.__name__


def test_connection(connector_type: str, config: dict[str, Any]) -> ConnectionTestResult:
    """Open a connection and run SELECT 1, reporting latency and server version."""
    warnings: list[str] = []
    if connector_type != "sqlite" and not config.get("password"):
        warnings.append("No password is configured for this connection.")

    start = time.perf_counter()
    try:
        engine = get_engine(connector_type, config)
        with engine.connect() as conn:
            probe = conn.execute(text("SELECT 1")).scalar_one()
            if probe != 1:
                return ConnectionTestResult(False, "Unexpected response from database.", warnings=warnings)
            version = _read_server_version(conn, connector_type)
    except SQLAlchemyError as exc:
        return ConnectionTestResult(False, f"Could not connect: {_safe_error(exc)}", warnings=warnings)
    except BadRequestError as exc:
        # Testing a connection should report what is wrong, including a bad
        # configuration, rather than raising at the operator who asked.
        return ConnectionTestResult(False, str(exc.detail), warnings=warnings)
    except Exception:  # noqa: BLE001 - surface a generic failure, never internals
        logger.exception("extraction_connection_test_failed connector_type=%s", connector_type)
        return ConnectionTestResult(False, "Connection failed.", warnings=warnings)

    latency_ms = (time.perf_counter() - start) * 1000.0
    return ConnectionTestResult(
        True,
        "Connected successfully. SELECT 1 succeeded.",
        latency_ms=latency_ms,
        server_version=version,
        warnings=warnings,
    )


def _read_server_version(conn: Any, connector_type: str) -> str | None:
    statement = "SELECT sqlite_version()" if connector_type == "sqlite" else "SELECT version()"
    try:
        value = conn.execute(text(statement)).scalar_one()
    except SQLAlchemyError:
        return None
    return str(value)[:200] if value is not None else None


def list_tables(connector_type: str, config: dict[str, Any]) -> list[TableRef]:
    """Discover tables and views the connection can see."""
    try:
        engine = get_engine(connector_type, config)
        inspector = inspect(engine)
        target_schema = config.get("schema") or None

        schemas: list[str | None]
        if connector_type == "sqlite":
            schemas = [None]
        elif target_schema:
            schemas = [target_schema]
        else:
            schemas = [inspector.default_schema_name]

        found: list[TableRef] = []
        for schema in schemas:
            for name in inspector.get_table_names(schema=schema):
                found.append(TableRef(schema=schema, name=name, kind="table"))
            for name in inspector.get_view_names(schema=schema):
                found.append(TableRef(schema=schema, name=name, kind="view"))
    except SQLAlchemyError as exc:
        raise BadRequestError(f"Could not list tables: {_safe_error(exc)}") from exc

    return sorted(found, key=lambda ref: (ref.schema or "", ref.name))


def list_columns(connector_type: str, config: dict[str, Any], *, table: str, schema: str | None = None) -> list[DiscoveredColumn]:
    """Describe one relation's columns, flagging primary keys."""
    try:
        engine = get_engine(connector_type, config)
        inspector = inspect(engine)
        effective_schema = schema or config.get("schema") or None
        columns = inspector.get_columns(table, schema=effective_schema)
        if not columns:
            raise BadRequestError(f"Table '{table}' has no readable columns or does not exist.")
        pk = set(inspector.get_pk_constraint(table, schema=effective_schema).get("constrained_columns") or [])
    except BadRequestError:
        raise
    except SQLAlchemyError as exc:
        raise BadRequestError(f"Could not describe table '{table}': {_safe_error(exc)}") from exc

    return [
        DiscoveredColumn(
            name=str(column["name"]),
            data_type=str(column.get("type")),
            nullable=bool(column.get("nullable", True)),
            primary_key=str(column["name"]) in pk,
        )
        for column in columns
    ]


def quote_identifier(connector_type: str, identifier: str) -> str:
    """Quote a table/column identifier for the dialect, escaping the quote char.

    Identifiers cannot be bound as parameters, so quoting is what keeps a table
    name chosen from discovery from being usable as an injection vector.
    """
    if not isinstance(identifier, str) or not identifier.strip():
        raise BadRequestError("Table, schema, and column names cannot be empty.")
    if "\x00" in identifier:
        raise BadRequestError("Identifier contains an invalid character.")
    quote = "`" if connector_type == "mysql" else '"'
    return f"{quote}{identifier.replace(quote, quote * 2)}{quote}"


def build_table_query(connector_type: str, *, table: str, schema: str | None) -> str:
    """Build `SELECT * FROM <relation>` with identifiers quoted for the dialect."""
    relation = quote_identifier(connector_type, table)
    if schema:
        relation = f"{quote_identifier(connector_type, schema)}.{relation}"
    return f"SELECT * FROM {relation}"


def read_dataframe(
    connector_type: str,
    config: dict[str, Any],
    *,
    sql: str,
    params: dict[str, Any] | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    validate_read_only: bool = True,
) -> ExtractionResult:
    """Stream a query into a DataFrame, stopping once `max_rows` is reached.

    Reading in chunks keeps peak memory bounded on wide tables and lets the row
    cap short-circuit before the full result set is materialised.
    """
    statement = ensure_read_only_select(sql) if validate_read_only else sql
    if max_rows <= 0:
        raise BadRequestError("max_rows must be greater than zero.")

    warnings: list[str] = []
    frames: list[pd.DataFrame] = []
    collected = 0
    truncated = False

    try:
        engine = get_engine(connector_type, config)
        with engine.connect().execution_options(stream_results=True) as conn:
            iterator = pd.read_sql_query(
                text(statement),
                conn,
                params=params or {},
                chunksize=max(1, min(chunk_size, max_rows)),
            )
            for chunk in iterator:
                remaining = max_rows - collected
                if len(chunk) >= remaining:
                    frames.append(chunk.iloc[:remaining])
                    collected += remaining
                    if len(chunk) > remaining:
                        truncated = True
                    else:
                        # The chunk landed exactly on the cap, so peek one more
                        # chunk to tell "finished" apart from "more to come".
                        following = next(iterator, None)
                        truncated = following is not None and len(following) > 0
                    break
                frames.append(chunk)
                collected += len(chunk)
    except BadRequestError:
        raise
    except SQLAlchemyError as exc:
        raise BadRequestError(f"Query failed: {_safe_error(exc)}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("extraction_read_failed connector_type=%s", connector_type)
        raise BadRequestError("Extraction query failed to execute.") from exc

    if frames:
        dataframe = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].reset_index(drop=True)
    else:
        dataframe = pd.DataFrame()

    if truncated:
        warnings.append(f"Result truncated at the {max_rows:,}-row limit.")
    if dataframe.empty:
        warnings.append("Query returned no rows.")

    return ExtractionResult(
        dataframe=dataframe,
        row_count=int(len(dataframe)),
        truncated=truncated,
        warnings=warnings,
    )
