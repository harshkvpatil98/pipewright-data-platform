from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np
import pandas as pd

from service_destinations.connectors.power_bi import fetch_power_bi_access_token
from service_destinations.postgres_writer import validate_table_identifier
from shared_python.errors import BadRequestError

PBI_BASE = "https://api.powerbi.com/v1.0/myorg"
ROW_BATCH_SIZE = 8000


@dataclass(frozen=True)
class PowerBiPublishOutcome:
    dataset_id: str
    workspace_id: str
    target_dataset_name: str
    target_table_name: str
    rows_published: int
    publish_mode: str  # created | replaced | appended


def validate_power_bi_target_dataset_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 200:
        raise BadRequestError("Target dataset name must be 1–200 characters.")
    if not re.match(r"^[\w\-. ]{1,200}$", name, flags=re.UNICODE):
        raise BadRequestError(
            "Target dataset name may only contain letters, digits, spaces, underscores, hyphens, and periods."
        )
    return name


def validate_workspace_id(raw: uuid.UUID | str) -> str:
    s = str(raw).strip()
    try:
        uuid.UUID(s)
    except ValueError as exc:
        raise BadRequestError("workspace_id must be a valid UUID.") from exc
    return s


def _sanitize_column_name(name: str) -> str:
    raw = str(name).strip()
    raw = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not raw:
        raw = "col"
    if raw[0].isdigit():
        raw = "c_" + raw
    return raw[:64]


def _unique_column_mapping(columns: list[Any]) -> dict[str, str]:
    seen: dict[str, bool] = {}
    mapping: dict[str, str] = {}
    for col in columns:
        orig = str(col)
        base = _sanitize_column_name(orig)
        candidate = base
        n = 2
        while candidate in seen:
            suffix = f"_{n}"
            candidate = (base[: max(1, 64 - len(suffix))] + suffix)[:64]
            n += 1
        seen[candidate] = True
        mapping[orig] = candidate
    return mapping


def _schema_type_lookup(schema_json: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not schema_json:
        return out
    cols = schema_json.get("columns")
    if not isinstance(cols, list):
        return out
    for c in cols:
        if not isinstance(c, dict):
            continue
        nm = c.get("name")
        it = c.get("inferred_type")
        if isinstance(nm, str) and isinstance(it, str):
            out[nm] = it.lower()
    return out


def _infer_pbi_datatype(
    series: pd.Series,
    original_name: str,
    schema_lookup: dict[str, str],
) -> str:
    hint = schema_lookup.get(original_name, "").lower()
    if hint in ("integer", "int", "int64", "long"):
        if series.isna().any() or not pd.api.types.is_integer_dtype(series):
            return "Double"
        return "Int64"
    if hint in ("float", "double", "decimal", "number"):
        return "Double"
    if hint in ("boolean", "bool"):
        return "Boolean"
    if hint in ("datetime", "date", "timestamp"):
        return "DateTime"
    if hint in ("string", "text", "object", "category"):
        return "String"

    if pd.api.types.is_bool_dtype(series):
        return "Boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DateTime"
    if pd.api.types.is_integer_dtype(series) and not series.isna().any():
        return "Int64"
    if pd.api.types.is_float_dtype(series) or pd.api.types.is_integer_dtype(series):
        return "Double"
    return "String"


def _rows_payload(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in df.replace({np.nan: None}).to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in record.items():
            if v is None:
                clean[k] = None
            elif isinstance(v, (pd.Timestamp, np.datetime64)):
                ts = pd.Timestamp(v)
                clean[k] = ts.isoformat() if pd.notna(ts) else None
            elif isinstance(v, (np.bool_, bool)):
                clean[k] = bool(v)
            elif isinstance(v, (np.integer,)):
                clean[k] = int(v)
            elif isinstance(v, (np.floating,)):
                clean[k] = None if (isinstance(v, float) and np.isnan(v)) else float(v)
            else:
                clean[k] = v
        rows.append(clean)
    return rows


def _list_datasets_in_group(client: httpx.Client, headers: dict[str, str], workspace_id: str) -> dict[str, Any]:
    r = client.get(f"{PBI_BASE}/groups/{workspace_id}/datasets", headers=headers)
    r.raise_for_status()
    return r.json()


def _find_dataset_id(datasets_body: dict[str, Any], name: str) -> str | None:
    values = datasets_body.get("value")
    if not isinstance(values, list):
        return None
    target = name.strip().lower()
    for d in values:
        if not isinstance(d, dict):
            continue
        dn = d.get("name")
        did = d.get("id")
        if isinstance(dn, str) and isinstance(did, str) and dn.strip().lower() == target:
            return did
    return None


def _delete_dataset(client: httpx.Client, headers: dict[str, str], workspace_id: str, dataset_id: str) -> None:
    r = client.delete(f"{PBI_BASE}/groups/{workspace_id}/datasets/{dataset_id}", headers=headers)
    r.raise_for_status()


def _create_push_dataset(
    client: httpx.Client,
    headers: dict[str, str],
    workspace_id: str,
    dataset_display_name: str,
    table_name: str,
    column_defs: list[dict[str, str]],
) -> str:
    body: dict[str, Any] = {
        "name": dataset_display_name,
        "defaultMode": "Push",
        "tables": [{"name": table_name, "columns": column_defs}],
    }
    r = client.post(
        f"{PBI_BASE}/groups/{workspace_id}/datasets",
        headers=headers,
        json=body,
    )
    r.raise_for_status()
    created = r.json()
    if not isinstance(created, dict) or not created.get("id"):
        raise BadRequestError("Power BI returned an unexpected create-dataset response.")
    return str(created["id"])


def _post_row_batches(
    client: httpx.Client,
    headers: dict[str, str],
    dataset_id: str,
    table_name: str,
    rows: list[dict[str, Any]],
) -> None:
    url = f"{PBI_BASE}/datasets/{dataset_id}/tables/{table_name}/rows"
    for i in range(0, len(rows), ROW_BATCH_SIZE):
        chunk = rows[i : i + ROW_BATCH_SIZE]
        r = client.post(url, headers=headers, json={"rows": chunk})
        r.raise_for_status()


def publish_dataframe_power_bi_push(
    *,
    power_bi_config: dict[str, Any],
    workspace_id: str,
    target_dataset_name: str,
    target_table_name: str,
    df: pd.DataFrame,
    write_mode: str,
    schema_json: dict[str, Any] | None = None,
) -> PowerBiPublishOutcome:
    """Push-dataset publish: create or reuse dataset, then POST rows (batched).

    **replace**: deletes an existing push dataset with the same name (case-insensitive) in the workspace, then recreates schema and loads all rows.

    **append**: if the dataset exists, appends rows to the target table; if not, creates the push dataset and loads rows.
    """
    if write_mode not in ("replace", "append"):
        raise BadRequestError('write_mode must be "replace" or "append".')

    dataset_display_name = validate_power_bi_target_dataset_name(target_dataset_name)
    ws = validate_workspace_id(workspace_id)
    tbl = validate_table_identifier(target_table_name)

    if len(df) == 0:
        raise BadRequestError("Dataset has no rows to publish.")

    schema_lookup = _schema_type_lookup(schema_json)
    col_map = _unique_column_mapping(list(df.columns))
    renamed = df.rename(columns=col_map)

    column_defs: list[dict[str, str]] = []
    for orig, pbi_col in col_map.items():
        dt = _infer_pbi_datatype(df[orig], str(orig), schema_lookup)
        column_defs.append({"name": pbi_col, "dataType": dt})

    rows = _rows_payload(renamed)

    try:
        token = fetch_power_bi_access_token(power_bi_config)
    except (httpx.HTTPError, ValueError) as exc:
        raise BadRequestError("Power BI authentication failed.") from exc

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=120.0) as client:
            existing_id = _find_dataset_id(_list_datasets_in_group(client, headers, ws), dataset_display_name)

            outcome_kind: str
            dataset_id: str

            if write_mode == "replace":
                if existing_id:
                    _delete_dataset(client, headers, ws, existing_id)
                dataset_id = _create_push_dataset(
                    client, headers, ws, dataset_display_name, tbl, column_defs
                )
                outcome_kind = "replaced" if existing_id else "created"
            else:
                if existing_id:
                    dataset_id = existing_id
                    outcome_kind = "appended"
                else:
                    dataset_id = _create_push_dataset(
                        client, headers, ws, dataset_display_name, tbl, column_defs
                    )
                    outcome_kind = "created"

            _post_row_batches(client, headers, dataset_id, tbl, rows)

    except httpx.HTTPStatusError as exc:
        raise BadRequestError("Power BI API rejected the publish request.") from exc
    except httpx.RequestError as exc:
        raise BadRequestError("Network error while calling Power BI.") from exc

    return PowerBiPublishOutcome(
        dataset_id=dataset_id,
        workspace_id=ws,
        target_dataset_name=dataset_display_name,
        target_table_name=tbl,
        rows_published=len(rows),
        publish_mode=outcome_kind,
    )
