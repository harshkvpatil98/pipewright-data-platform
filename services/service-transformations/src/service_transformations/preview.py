from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_ingestion.parsers import parse_tabular_file
from service_projects.contracts import ensure_owned_project
from service_transformations.executor import apply_transformation_steps
from service_transformations.schemas import TransformationPreviewRequest, TransformationPreviewResponse
from service_transformations.tabular import build_schema_summary, json_preview_rows
from shared_python.errors import BadRequestError


def preview_dataset_transformations(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: TransformationPreviewRequest,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any | None = None,
) -> TransformationPreviewResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("Dataset has no stored file artifact to preview.")

    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise BadRequestError("Stored dataset file was not found.") from exc
    except OSError as exc:
        raise BadRequestError(f"Unable to read dataset file: {exc}") from exc

    parsed = parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type)
    source_frame = parsed.dataframe.copy()

    limit = getattr(settings, "preview_row_limit", 50) if settings is not None else 50
    if not isinstance(limit, int) or limit < 1:
        limit = 50

    transformed, warnings = apply_transformation_steps(source_frame, payload.steps)

    schema_before = build_schema_summary(source_frame)
    schema_after = build_schema_summary(transformed)

    preview_columns = [str(column) for column in transformed.columns]
    preview_rows = json_preview_rows(transformed, limit)

    return TransformationPreviewResponse(
        preview_rows=preview_rows,
        preview_columns=preview_columns,
        row_count_before=int(len(source_frame)),
        row_count_after=int(len(transformed)),
        column_count_before=int(len(source_frame.columns)),
        column_count_after=int(len(transformed.columns)),
        schema_before=schema_before,
        schema_after=schema_after,
        warnings=warnings,
    )
