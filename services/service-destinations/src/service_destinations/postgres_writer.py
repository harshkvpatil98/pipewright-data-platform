from __future__ import annotations

import re
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, types as satypes
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from shared_python.errors import BadRequestError


def validate_table_identifier(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 63:
        raise BadRequestError("Table name must be 1–63 characters.")
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise BadRequestError(
            "Table name must start with a letter or underscore and contain only letters, digits, and underscores."
        )
    if name.lower() in {"select", "table", "where", "from", "group", "order"}:
        raise BadRequestError("This table name is reserved; choose another.")
    return name


def _sanitize_column(name: str) -> str:
    raw = str(name).strip()
    raw = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not raw:
        raw = "col"
    if raw[0].isdigit():
        raw = "c_" + raw
    return raw[:63]


def _dtype_map(df: pd.DataFrame) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_bool_dtype(s):
            mapping[col] = satypes.Boolean()
        elif pd.api.types.is_integer_dtype(s):
            mapping[col] = satypes.BigInteger()
        elif pd.api.types.is_float_dtype(s):
            mapping[col] = satypes.Double()
        elif pd.api.types.is_datetime64_any_dtype(s):
            mapping[col] = satypes.TIMESTAMP(timezone=True)
        else:
            mapping[col] = satypes.Text()
    return mapping


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {c: _sanitize_column(str(c)) for c in out.columns}
    out = out.rename(columns=rename)
    # de-duplicate column names if sanitization collides
    seen: dict[str, int] = {}
    new_cols = []
    for c in out.columns:
        base = str(c)
        if base in seen:
            seen[base] += 1
            new_cols.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 0
            new_cols.append(base)
    out.columns = new_cols
    return out


def write_dataframe_to_postgres(
    df: pd.DataFrame,
    *,
    config: dict[str, Any],
    table_name: str,
    write_mode: str,
) -> int:
    """
    Write dataframe using SQLAlchemy + pandas to_sql.
    Does not log or return passwords.
    """
    host = config["host"]
    port = int(config.get("port", 5432))
    database = config["database"]
    user = config["username"]
    password = config["password"]
    sslmode = str(config.get("ssl_mode", "prefer"))

    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"sslmode": sslmode},
    )
    schema = config.get("schema")
    if schema is not None and isinstance(schema, str) and schema.strip():
        schema = schema.strip()
    else:
        schema = None

    if_exists = "replace" if write_mode == "replace" else "append"
    frame = _prepare_frame(df)
    dtype = _dtype_map(frame)

    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 30})
        with engine.begin() as conn:
            frame.to_sql(
                name=table_name,
                con=conn,
                schema=schema,
                if_exists=if_exists,
                index=False,
                dtype=dtype,
                chunksize=5000,
                method="multi",
            )
    except SQLAlchemyError as exc:
        msg = str(exc).splitlines()[0][:500]
        raise BadRequestError(f"PostgreSQL write failed: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError("PostgreSQL write failed.") from exc

    return int(len(frame))
