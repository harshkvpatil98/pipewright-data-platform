"""Delivering a dataset to a destination, with a look first.

One entry point for every kind of destination that receives data:

- PostgreSQL and MySQL tables, by `sql_writer` (replace, append, update
  matching rows).
- Files in S3 or an S3-compatible store, or in a folder inside the server's
  shared files folder, as CSV or Parquet, by the connector SDK's own file
  connectors -- the same code that reads files there.

`preview_delivery` says what would be written (the table and its columns and
types, or the file and its format) without writing anything or connecting.
`deliver_dataset` writes it and records the delivery as a run, so the Runs
page and the notification say what went where.

From the page, `start_delivery` writes a small dataset at once and hands a
large one to the background worker (A7, X3), so a long write never outlasts
the request; the dialog follows the run until it finishes.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_destinations.at_rest_config import destination_config_for_internal_use
from service_destinations.models import DestinationConfig
from service_destinations.publish_schemas import (
    DeliveryColumn,
    DeliveryPreview,
    DeliveryRequest,
    DeliveryResult,
)
from service_destinations.service import get_destination_model
from service_destinations.sql_writer import ENGINES, column_kind, plan_table, plural, write_frame
from service_notifications.outcomes import notify_manual_dataset_publish
from service_pipeline_runs import background
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import ApplicationError, BadRequestError, NotFoundError
from shared_python.server_files import OutsideServerFiles, confine

RUN_TYPE = "dataset_delivery"
#: Up to this many rows a delivery from the page is written in the request;
#: above it the background worker writes it.
IN_REQUEST_ROWS = 50_000
FILE_TYPES = {"s3": "S3", "local_export": "Server folder"}
LABELS = {**ENGINES, **FILE_TYPES}


def _label(destination: DestinationConfig) -> str:
    if destination.destination_type == "s3" and (destination.config_json or {}).get("endpoint_url"):
        return "S3-compatible storage"
    return LABELS.get(destination.destination_type, destination.destination_type)


def _load_frame(dataset: Any, storage: Any) -> pd.DataFrame:
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("This dataset has no stored data to deliver yet.")
    try:
        raw = storage.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise NotFoundError("This dataset's stored file is missing.") from exc
    from service_ingestion.read_copy import frame_of

    return frame_of(storage, dataset.file_path, raw, file_type=dataset.file_type, spec=dataset.ingest_spec_json)


def _file_name(raw: str | None, dataset_name: str, file_format: str) -> str:
    """A plain file name, optionally in sub-folders, never climbing out of them."""
    name = (raw or "").strip() or re.sub(r"[^A-Za-z0-9._-]+", "-", dataset_name).strip("-.") or "dataset"
    parts = [part for part in re.split(r"[\\/]+", name) if part]
    if any(part in (".", "..") for part in parts) or not parts:
        raise BadRequestError("A file name cannot contain . or .. as a folder.")
    cleaned = "/".join(re.sub(r"[^A-Za-z0-9._ -]+", "-", part).strip() for part in parts)
    extension = f".{file_format}"
    return cleaned if cleaned.lower().endswith(extension) else f"{cleaned}{extension}"


def _file_target(destination: DestinationConfig, config: dict[str, Any], file_name: str) -> str:
    if destination.destination_type == "s3":
        prefix = str(config.get("prefix") or "").strip("/")
        key = f"{prefix}/{file_name}" if prefix else file_name
        return f"s3://{config['bucket']}/{key}"
    try:
        folder = confine(str(config.get("path") or ""))
    except OutsideServerFiles as exc:
        raise BadRequestError(str(exc)) from exc
    return str(folder / file_name)


def _file_columns(frame: pd.DataFrame) -> list[DeliveryColumn]:
    return [
        DeliveryColumn(name=str(column), source=str(column), type=column_kind(frame[column]), key=False)
        for column in frame.columns
    ]


def _check_request(destination: DestinationConfig, payload: DeliveryRequest) -> None:
    """What can be refused before any data is read."""
    if destination.status != "active":
        raise BadRequestError("This destination is turned off.")
    kind = destination.destination_type
    if kind in ENGINES:
        if not (payload.table_name or "").strip():
            raise BadRequestError("Name the table to deliver to.")
    elif kind in FILE_TYPES:
        if payload.mode == "update":
            raise BadRequestError("Files can be replaced or added to; updating matching rows needs a database.")
    else:
        raise BadRequestError("This destination does not receive datasets.")


def _plan(destination: DestinationConfig, frame: pd.DataFrame, payload: DeliveryRequest, dataset_name: str):
    _check_request(destination, payload)
    kind = destination.destination_type
    if kind in ENGINES:
        config = dict(destination.config_json or {})
        plan = plan_table(
            frame, destination_type=kind, table=payload.table_name or "", schema=config.get("schema"),
            mode=payload.mode, key_columns=payload.key_columns,
        )
        columns = [DeliveryColumn(**column.to_dict()) for column in plan.columns]
        return "table", plan.qualified, columns, list(plan.notes), plan
    if kind in FILE_TYPES:
        file_name = _file_name(payload.file_name, dataset_name, payload.file_format)
        target = _file_target(destination, dict(destination.config_json or {}), file_name)
        notes = [
            "The file is written again with exactly this data."
            if payload.mode == "replace"
            else "The rows are added to the file; it is created if it is not there."
        ]
        if payload.file_format == "parquet":
            notes.append("Parquet keeps each column's type; CSV is easier to open in a spreadsheet.")
        return "file", target, _file_columns(frame), notes, file_name
    raise BadRequestError("This destination does not receive datasets.")


def _visible(db: Session, project_id: uuid.UUID, dataset: Any, current_user: UserRead, frame: pd.DataFrame) -> pd.DataFrame:
    """What leaves for a destination is no more than the sender may see (A6, W1)."""
    from service_enterprise.policy_view import Reader, narrow_frame

    return narrow_frame(db, project_id, dataset.id, Reader.for_user(db, project_id, current_user), frame)


def preview_delivery(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, payload: DeliveryRequest,
    current_user: UserRead, storage: Any,
) -> DeliveryPreview:
    ensure_owned_project(db, project_id, current_user.id)
    destination = get_destination_model(db, project_id, payload.destination_id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    frame = _visible(db, project_id, dataset, current_user, _load_frame(dataset, storage))
    kind, target, columns, notes, _ = _plan(destination, frame, payload, dataset.name)
    return DeliveryPreview(
        destination_id=destination.id, destination_name=destination.name, destination_label=_label(destination),
        kind=kind, target=target, mode=payload.mode, rows=int(len(frame)), columns=columns, notes=notes,
    )


def _write_file(destination: DestinationConfig, config: dict[str, Any], frame: pd.DataFrame,
                file_name: str, payload: DeliveryRequest) -> tuple[int, list[str]]:
    from service_connectors import ConnectorError, StreamRef, get

    if destination.destination_type == "s3":
        connector = get("s3")
        prefix = str(config.get("prefix") or "").strip("/")
        path = f"{prefix}/{file_name}" if prefix else file_name
        connector_config = {
            "bucket": config["bucket"], "region": config.get("region") or "us-east-1",
            "endpoint_url": config.get("endpoint_url") or None,
            "access_key_id": config["access_key_id"], "secret_access_key": config["secret_access_key"],
            "format": payload.file_format,
        }
    else:
        connector = get("local_files")
        path = file_name
        folder = confine(str(config.get("path") or ""))
        (folder / file_name).parent.mkdir(parents=True, exist_ok=True)
        connector_config = {"directory": str(folder), "format": payload.file_format}
    try:
        result = connector.write(connector_config, StreamRef(name=path, kind="file"), frame, mode=payload.mode)
    except ConnectorError as exc:
        raise BadRequestError(exc.message) from exc
    return int(result.rows_written), list(result.warnings)


def deliver_dataset(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, payload: DeliveryRequest,
    current_user: UserRead, storage: Any, *, notify_on_complete: bool = True,
) -> DeliveryResult:
    """Deliver now, in this process (a workflow task, a test, a small dataset from the page)."""
    ensure_owned_project(db, project_id, current_user.id)
    destination = get_destination_model(db, project_id, payload.destination_id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    frame = _visible(db, project_id, dataset, current_user, _load_frame(dataset, storage))
    kind, target, _columns, _notes, plan_or_file = _plan(destination, frame, payload, dataset.name)

    run = create_pipeline_run(db, project_id=project_id, current_user=current_user, run_type=RUN_TYPE,
                              logs_json={"events": [background.event("queued", f"Delivery to {target} accepted.")]})
    mark_pipeline_run_running(db, run=run)
    return _write(db, run=run, destination=destination, dataset=dataset, frame=frame, payload=payload,
                  kind=kind, target=target, plan_or_file=plan_or_file, notify_on_complete=notify_on_complete)


def _write(
    db: Session, *, run: Any, destination: DestinationConfig, dataset: Any, frame: pd.DataFrame,
    payload: DeliveryRequest, kind: str, target: str, plan_or_file: Any, notify_on_complete: bool,
) -> DeliveryResult:
    """Write the planned delivery and finish its run."""
    events = list((run.logs_json or {}).get("events", []))
    summary: dict[str, Any] = {
        "dataset_id": str(dataset.id), "dataset_name": dataset.name,
        "destination": {"id": str(destination.id), "name": destination.name,
                        "type": destination.destination_type, "label": _label(destination)},
        "target": target, "mode": payload.mode, "kind": kind,
        "file_format": payload.file_format if kind == "file" else None,
        "key_columns": list(payload.key_columns or []),
    }

    try:
        config = destination_config_for_internal_use(destination.destination_type, dict(destination.config_json or {}))
        if kind == "table":
            outcome = write_frame(frame, plan=plan_or_file, config=config)
            summary.update(rows_written=outcome.rows_written, rows_updated=outcome.rows_updated,
                           rows_added=outcome.rows_added, table_created=outcome.table_created,
                           warnings=outcome.warnings)
        else:
            rows, warnings = _write_file(destination, config, frame, plan_or_file, payload)
            summary.update(rows_written=rows, rows_updated=0, rows_added=rows, table_created=None, warnings=warnings)
    except ApplicationError as exc:
        events.append(background.event("failed", str(exc.detail)))
        summary["error"] = str(exc.detail)
        run_read = mark_pipeline_run_failed(db, run=run, summary_json=summary, logs_json={"events": events})
        if notify_on_complete:
            notify_manual_dataset_publish(db, run_read=run_read, success=False)
        db.commit()
        return DeliveryResult(run_id=run.id, status="failed", target=target, mode=payload.mode,
                              message=str(exc.detail), rows_written=0, rows_updated=0, rows_added=0)

    events.append(background.event("succeeded", f"Wrote {plural(summary['rows_written'], 'row')} to {target}."))
    run_read = mark_pipeline_run_succeeded(db, run=run, summary_json=summary, logs_json={"events": events})
    if notify_on_complete:
        notify_manual_dataset_publish(db, run_read=run_read, success=True)
    db.commit()
    return DeliveryResult(
        run_id=run.id, status="succeeded", target=target, mode=payload.mode,
        message=f"Delivered {plural(summary['rows_written'], 'row')} to {target}.",
        rows_written=summary["rows_written"], rows_updated=summary["rows_updated"],
        rows_added=summary["rows_added"], table_created=summary.get("table_created"),
        warnings=list(summary.get("warnings") or []),
    )


def _target_words(destination: DestinationConfig, payload: DeliveryRequest, dataset_name: str) -> str:
    """Where it is going, said before the data is read."""
    if destination.destination_type in ENGINES:
        schema = (destination.config_json or {}).get("schema")
        table = (payload.table_name or "").strip()
        return f"{schema}.{table}" if schema else table
    return _file_target(destination, dict(destination.config_json or {}),
                        _file_name(payload.file_name, dataset_name, payload.file_format))


def start_delivery(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, payload: DeliveryRequest,
    current_user: UserRead, storage: Any,
) -> DeliveryResult:
    """A delivery from the page: written now when small, by the worker when large."""
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    if (dataset.row_count or 0) <= IN_REQUEST_ROWS:
        return deliver_dataset(db, project_id, dataset_id, payload, current_user, storage)

    destination = get_destination_model(db, project_id, payload.destination_id)
    _check_request(destination, payload)
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("This dataset has no stored data to deliver yet.")
    target = _target_words(destination, payload, dataset.name)
    run = create_pipeline_run(db, project_id=project_id, current_user=current_user, run_type=RUN_TYPE,
                              logs_json={"events": []})
    background.queue(
        db, run=run,
        request={"dataset_id": str(dataset.id), "delivery": payload.model_dump(mode="json")},
        message=f"Waiting for the background worker to deliver {plural(dataset.row_count or 0, 'row')} to {target}.",
    )
    return DeliveryResult(
        run_id=run.id, status="queued", target=target, mode=payload.mode,
        message=f"Delivering {plural(dataset.row_count or 0, 'row')} to {target} in the background.",
        rows_written=0, rows_updated=0, rows_added=0,
    )


def deliver_queued(db: Session, run: Any, storage_backend: Any, settings: Any) -> None:
    """The worker's half of a delivery started from the page."""
    from service_auth.models import User

    owner = db.get(User, run.triggered_by_user_id)
    if owner is None:
        raise BadRequestError("The person who started this delivery no longer has an account.")
    current_user = UserRead.model_validate(owner, from_attributes=True)
    request = run.request_json or {}
    payload = DeliveryRequest.model_validate(request["delivery"])
    dataset = get_dataset_model_for_project(db, run.project_id, uuid.UUID(request["dataset_id"]))
    destination = get_destination_model(db, run.project_id, payload.destination_id)

    background.progress(db, run, "reading", f"Reading {dataset.name}.")
    # What leaves is no more than the person who started it may see, as in the request.
    frame = _visible(db, run.project_id, dataset, current_user, _load_frame(dataset, storage_backend))
    kind, target, _columns, _notes, plan_or_file = _plan(destination, frame, payload, dataset.name)
    background.progress(db, run, "writing", f"Writing {plural(len(frame), 'row')} to {target}.")
    _write(db, run=run, destination=destination, dataset=dataset, frame=frame, payload=payload,
           kind=kind, target=target, plan_or_file=plan_or_file, notify_on_complete=True)


background.register(RUN_TYPE, deliver_queued)
