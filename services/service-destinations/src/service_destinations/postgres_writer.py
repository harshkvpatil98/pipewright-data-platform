from __future__ import annotations

import re
from typing import Any

import pandas as pd

from service_destinations.sql_writer import plan_table, write_frame
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


def write_dataframe_to_postgres(
    df: pd.DataFrame,
    *,
    config: dict[str, Any],
    table_name: str,
    write_mode: str,
) -> int:
    """Replace or append to a PostgreSQL table; the scheduled and workflow path.

    Delegates to `sql_writer`, the one writer for database deliveries, so a
    scheduled delivery types its columns from the values (ids as bigint,
    amounts as double) exactly as a delivery from the dataset page does.
    """
    schema = config.get("schema") if isinstance(config.get("schema"), str) and config["schema"].strip() else None
    plan = plan_table(df, destination_type="postgres", table=table_name, schema=schema, mode=write_mode, key_columns=None)
    return write_frame(df, plan=plan, config=config).rows_written
