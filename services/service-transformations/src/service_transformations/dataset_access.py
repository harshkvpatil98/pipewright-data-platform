"""Build the StepContext used by multi-input steps (join, union).

Resolution is always scoped to the current project and goes through
`get_dataset_model_for_project`, so a step cannot reach a dataset belonging to
another project by supplying its id.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_datasets.service import get_dataset_model_for_project
from service_ingestion.parsers import parse_tabular_file
from service_transformations.steps.context import StepContext
from shared_python.errors import BadRequestError


def build_step_context(
    db: Session,
    *,
    project_id: uuid.UUID,
    storage_backend: Any,
    max_bytes: int | None = None,
) -> StepContext:
    # Datasets are re-read per step; caching avoids paying storage + parse twice
    # when the same dataset is joined more than once in a pipeline.
    cache: dict[str, pd.DataFrame] = {}

    def _coerce_id(dataset_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(dataset_id))
        except ValueError as exc:
            raise BadRequestError(f"'{dataset_id}' is not a valid dataset id.") from exc

    def resolve(dataset_id: str) -> pd.DataFrame:
        key = str(dataset_id)
        if key in cache:
            return cache[key].copy()

        dataset = get_dataset_model_for_project(db, project_id, _coerce_id(key))
        if not dataset.file_path or not dataset.file_type:
            raise BadRequestError(f"Dataset '{dataset.name}' has no stored file artifact to read.")

        try:
            file_bytes = storage_backend.read_bytes(dataset.file_path)
        except FileNotFoundError as exc:
            raise BadRequestError(f"Stored file for dataset '{dataset.name}' was not found.") from exc
        except OSError as exc:
            raise BadRequestError(f"Unable to read dataset '{dataset.name}': {exc}") from exc

        if max_bytes is not None and len(file_bytes) > max_bytes:
            raise BadRequestError(
                f"Dataset '{dataset.name}' exceeds the configured maximum size for this operation."
            )

        frame = parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type).dataframe
        cache[key] = frame
        return frame.copy()

    def describe(dataset_id: str) -> str:
        dataset = get_dataset_model_for_project(db, project_id, _coerce_id(str(dataset_id)))
        return dataset.name

    return StepContext(resolve_dataset=resolve, describe_dataset=describe)
