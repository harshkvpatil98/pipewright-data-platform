from __future__ import annotations

import time
from typing import Any

import psycopg
from psycopg import OperationalError, ProgrammingError
from psycopg import sql as psql

from shared_python.errors import BadRequestError


def check_postgres_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    """
    Open a short-lived connection and run SELECT 1.
    Never logs passwords.
    """
    warnings: list[str] = []
    host = config.get("host")
    port = int(config.get("port", 5432))
    dbname = config.get("database")
    user = config.get("username")
    password = config.get("password")
    sslmode = config.get("ssl_mode", "prefer")

    if not all(isinstance(x, str) for x in (host, dbname, user, password)):
        raise BadRequestError("Invalid PostgreSQL configuration (missing connection fields).")

    conninfo = (
        f"host={host} port={port} dbname={dbname} user={user} password={password} "
        f"sslmode={sslmode} connect_timeout=8"
    )

    start = time.perf_counter()
    try:
        with psycopg.connect(conninfo, connect_timeout=8) as conn:
            if config.get("schema"):
                with conn.cursor() as cur:
                    cur.execute(psql.SQL("SET search_path TO {}").format(psql.Identifier(config["schema"])))
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                if row is None or row[0] != 1:
                    return False, "Unexpected response from database.", None, warnings
    except OperationalError as exc:
        msg = str(exc).splitlines()[0][:500]
        return False, f"Could not connect: {msg}", None, warnings
    except ProgrammingError as exc:
        msg = str(exc).splitlines()[0][:500]
        return False, f"Database error: {msg}", None, warnings
    except Exception as exc:  # noqa: BLE001
        return False, "Connection failed.", None, warnings

    latency_ms = (time.perf_counter() - start) * 1000.0
    return True, "Connected successfully. SELECT 1 succeeded.", latency_ms, warnings
