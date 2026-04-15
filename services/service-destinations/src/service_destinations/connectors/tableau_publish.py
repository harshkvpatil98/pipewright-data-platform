from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np
import pandas as pd
from tableauhyperapi import (
    Connection,
    CreateMode,
    HyperProcess,
    Inserter,
    Nullability,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)
from tableauhyperapi.hyperexception import HyperException

from service_destinations.connectors.tableau import tableau_sign_in
from shared_python.errors import BadRequestError


@dataclass(frozen=True)
class TableauPublishOutcome:
    datasource_id: str
    site_id: str
    tableau_project_id: str
    datasource_name: str
    rows_published: int
    publish_mode: str  # replace | create_only (echoes request write_mode)


def validate_tableau_datasource_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 200:
        raise BadRequestError("Datasource name must be 1–200 characters.")
    if not re.match(r"^[\w\-. ]{1,200}$", name, flags=re.UNICODE):
        raise BadRequestError(
            "Datasource name may only contain letters, digits, spaces, underscores, hyphens, and periods."
        )
    return name


def _base_and_ver(config: dict[str, Any]) -> tuple[str, str]:
    return str(config["server_url"]).rstrip("/"), str(config.get("api_version", "3.21"))


def _sanitize_hyper_column(name: str) -> str:
    raw = str(name).strip()
    raw = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not raw:
        raw = "col"
    if raw[0].isdigit():
        raw = "c_" + raw
    return raw[:63]


def _unique_hyper_columns(columns: list[Any]) -> dict[str, str]:
    seen: dict[str, bool] = {}
    mapping: dict[str, str] = {}
    for col in columns:
        orig = str(col)
        base = _sanitize_hyper_column(orig)
        candidate = base
        n = 2
        while candidate in seen:
            suffix = f"_{n}"
            candidate = (base[: max(1, 63 - len(suffix))] + suffix)[:63]
            n += 1
        seen[candidate] = True
        mapping[orig] = candidate
    return mapping


def _sql_type_for_series(series: pd.Series) -> Any:
    if pd.api.types.is_bool_dtype(series):
        return SqlType.bool()
    if pd.api.types.is_datetime64_any_dtype(series):
        return SqlType.timestamp()
    if pd.api.types.is_integer_dtype(series):
        return SqlType.big_int()
    if pd.api.types.is_float_dtype(series):
        return SqlType.double()
    return SqlType.text()


def _cell_for_hyper(value: Any, series: pd.Series) -> Any:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if pd.api.types.is_datetime64_any_dtype(series):
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    if pd.api.types.is_bool_dtype(series):
        return bool(value)
    if pd.api.types.is_integer_dtype(series):
        return int(value)
    if pd.api.types.is_float_dtype(series):
        return float(value)
    return str(value)


def dataframe_to_hyper_bytes(df: pd.DataFrame) -> bytes:
    if len(df) == 0:
        raise BadRequestError("Dataset has no rows to publish.")
    df2 = df.reset_index(drop=True)
    col_map = _unique_hyper_columns(list(df2.columns))
    df2 = df2.rename(columns=col_map)

    columns: list[TableDefinition.Column] = []
    for orig, hname in col_map.items():
        series = df[orig]
        st = _sql_type_for_series(series)
        columns.append(TableDefinition.Column(hname, st, Nullability.NULLABLE))

    table_def = TableDefinition(
        table_name=TableName("Extract", "Extract"),
        columns=columns,
    )

    path = tempfile.mktemp(suffix=".hyper")
    try:
        with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
            with Connection(
                endpoint=hyper.endpoint,
                database=path,
                create_mode=CreateMode.CREATE_AND_REPLACE,
            ) as connection:
                connection.catalog.create_schema("Extract")
                connection.catalog.create_table(table_def)
                with Inserter(connection, table_def) as inserter:
                    for i in range(len(df2)):
                        row_vals = tuple(
                            _cell_for_hyper(df2.at[i, h], df[str(orig)])
                            for orig, h in col_map.items()
                        )
                        inserter.add_row(row_vals)
                    inserter.execute()
        with open(path, "rb") as f:
            return f.read()
    except HyperException as exc:
        raise BadRequestError("Failed to build Tableau Hyper extract for publish.") from exc
    finally:
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


def verify_tableau_project(
    *,
    config: dict[str, Any],
    token: str,
    site_id: str,
    project_id: str,
) -> None:
    base, ver = _base_and_ver(config)
    url = f"{base}/api/{ver}/sites/{site_id}/projects/{project_id}"
    headers = {"X-Tableau-Auth": token, "Accept": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()


def publish_hyper_datasource(
    *,
    config: dict[str, Any],
    token: str,
    site_id: str,
    tableau_project_id: str,
    datasource_name: str,
    hyper_bytes: bytes,
    write_mode: str,
) -> TableauPublishOutcome:
    if write_mode not in ("replace", "create_only"):
        raise BadRequestError('write_mode must be "replace" or "create_only".')

    base, ver = _base_and_ver(config)
    safe_name = validate_tableau_datasource_name(datasource_name)
    overwrite = "true" if write_mode == "replace" else "false"

    payload = {
        "datasource": {
            "name": safe_name,
            "project": {"id": tableau_project_id},
        }
    }
    url = f"{base}/api/{ver}/sites/{site_id}/datasources"
    headers = {"X-Tableau-Auth": token, "Accept": "application/json"}

    file_name = re.sub(r"[^\w\-.]+", "_", safe_name).strip("._") or "dataset"
    file_name = f"{file_name[:120]}.hyper"

    try:
        with httpx.Client(timeout=300.0) as client:
            r = client.post(
                url,
                headers=headers,
                params={"overwrite": overwrite},
                files={
                    "request_payload": (None, json.dumps(payload), "application/json"),
                    "tableau_file": (file_name, hyper_bytes, "application/octet-stream"),
                },
            )
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPStatusError as exc:
        raise BadRequestError("Tableau Server rejected the datasource publish request.") from exc
    except httpx.RequestError as exc:
        raise BadRequestError("Network error while publishing to Tableau.") from exc

    ds = body.get("datasource") if isinstance(body, dict) else None
    if not isinstance(ds, dict) or not ds.get("id"):
        raise BadRequestError("Tableau returned an unexpected publish response.")

    return TableauPublishOutcome(
        datasource_id=str(ds["id"]),
        site_id=site_id,
        tableau_project_id=tableau_project_id,
        datasource_name=safe_name,
        rows_published=0,
        publish_mode=write_mode,
    )


def publish_dataframe_to_tableau_datasource(
    *,
    tableau_config: dict[str, Any],
    tableau_project_id: str,
    datasource_name: str,
    df: pd.DataFrame,
    write_mode: str,
) -> TableauPublishOutcome:
    """Build a single-table Hyper extract and publish it as a datasource on Tableau Server/Cloud."""
    try:
        token, site_id = tableau_sign_in(tableau_config)
    except (httpx.HTTPError, ValueError) as exc:
        raise BadRequestError("Tableau authentication failed.") from exc

    verify_tableau_project(
        config=tableau_config,
        token=token,
        site_id=site_id,
        project_id=tableau_project_id,
    )

    hyper_bytes = dataframe_to_hyper_bytes(df)
    rows = int(len(df))
    outcome = publish_hyper_datasource(
        config=tableau_config,
        token=token,
        site_id=site_id,
        tableau_project_id=tableau_project_id,
        datasource_name=datasource_name,
        hyper_bytes=hyper_bytes,
        write_mode=write_mode,
    )
    return TableauPublishOutcome(
        datasource_id=outcome.datasource_id,
        site_id=outcome.site_id,
        tableau_project_id=outcome.tableau_project_id,
        datasource_name=outcome.datasource_name,
        rows_published=rows,
        publish_mode=outcome.publish_mode,
    )
