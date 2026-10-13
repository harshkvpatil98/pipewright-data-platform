"""Downloading a dataset, or any version of it, as CSV or Parquet.

This hands every row to a person, so it applies the project's row and column
policies for that person's role (`service_enterprise.visible_frame`): a
download must never show more than the policies allow. Versions whose data
the retention policy has removed say so rather than failing obscurely.
"""

from __future__ import annotations

import io
import re
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import DatasetVersion
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

FORMATS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "parquet": ("application/vnd.apache.parquet", "parquet"),
}


def _file_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return stem[:120] or "dataset"


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    try:
        frame.to_parquet(buffer, index=False)
    except Exception:  # noqa: BLE001 - mixed values in one object column
        # Parquet needs one type per column. A column holding numbers and text
        # is written as text, which keeps every value rather than refusing.
        coerced = frame.copy()
        for column in coerced.columns:
            if coerced[column].dtype == object:
                coerced[column] = coerced[column].map(lambda value: None if pd.isna(value) else str(value))
        buffer = io.BytesIO()
        coerced.to_parquet(buffer, index=False)
    return buffer.getvalue()


def download_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    storage: Any,
    *,
    export_format: str = "csv",
    version_number: int | None = None,
) -> tuple[bytes, str, str]:
    """(content, media type, file name) for one dataset or one of its versions."""
    if export_format not in FORMATS:
        raise BadRequestError(f"Downloads are CSV or Parquet, not '{export_format}'.")
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    if version_number is None:
        file_path, file_type = dataset.file_path, dataset.file_type
        suffix = ""
    else:
        version = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id, DatasetVersion.version_number == version_number
            )
        )
        if version is None:
            raise NotFoundError(f"This dataset has no version {version_number}.")
        if version.retention_state == "pruned" or version.artifact_removed_at is not None:
            raise BadRequestError(
                f"Version {version_number}'s data was removed by the retention policy; its record remains."
            )
        file_path, file_type = version.file_path, version.file_type
        suffix = f"-v{version_number}"

    if not file_path or not file_type:
        raise BadRequestError("This dataset has no stored data to download yet.")
    try:
        raw = storage.read_bytes(file_path)
    except FileNotFoundError as exc:
        raise NotFoundError("This dataset's stored file is missing.") from exc

    from service_enterprise.service import visible_frame
    from service_ingestion.parsers import parse_tabular_file

    frame = parse_tabular_file(file_bytes=raw, file_type=file_type).dataframe
    frame, _applied = visible_frame(db, project_id, dataset.id, current_user, frame)

    media_type, extension = FORMATS[export_format]
    content = frame.to_csv(index=False).encode("utf-8") if export_format == "csv" else _parquet_bytes(frame)
    return content, media_type, f"{_file_stem(dataset.name)}{suffix}.{extension}"
