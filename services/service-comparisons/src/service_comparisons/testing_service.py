from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_datasets.service import get_dataset_model_for_project
from service_ingestion.parsers import parse_tabular_file
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_comparisons.schemas import (
    DatasetStatisticalTestRequest,
    DatasetStatisticalTestResult,
    StatisticalTestDatasetSide,
)
from service_comparisons.statistical_tests import (
    chi_square_two_sample_distributions,
    two_proportion_z_test,
    welch_t_test,
)


def _schema_column_names(dataset: Dataset) -> set[str]:
    sj = dataset.schema_json or {}
    names: set[str] = set()
    for c in sj.get("columns", []):
        if isinstance(c, dict) and c.get("name") is not None:
            names.add(str(c["name"]))
    return names


def _resolve_column(dataframe: pd.DataFrame, name: str) -> str:
    cols = list(dataframe.columns)
    if name in cols:
        return name
    lower_map = {str(c).lower(): c for c in cols}
    if name.lower() in lower_map:
        return str(lower_map[name.lower()])
    raise BadRequestError(f'Column "{name}" was not found in the dataset file.')


def _load_dataframe(dataset: Dataset, storage_backend: Any) -> pd.DataFrame:
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("Dataset has no stored file artifact to analyze.")
    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise NotFoundError(
            "This dataset's stored file is missing. The dataset record still exists, so re-uploading the file restores it."
        ) from exc
    except OSError as exc:
        raise BadRequestError(f"Unable to read dataset file: {exc}") from exc
    parsed = parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type)
    return parsed.dataframe


def _column_in_schema(names: set[str], requested: str) -> bool:
    if requested in names:
        return True
    rl = requested.lower()
    return any(n.lower() == rl for n in names)


def _validate_column_declared(left: Dataset, right: Dataset, logical_name: str) -> None:
    sl = _schema_column_names(left)
    sr = _schema_column_names(right)
    if not sl or not sr:
        return
    if not (_column_in_schema(sl, logical_name) and _column_in_schema(sr, logical_name)):
        raise BadRequestError(
            f'Column "{logical_name}" must appear in both datasets\' stored schema metadata.'
        )


def run_dataset_statistical_test(
    db: Session,
    *,
    project_id: uuid.UUID,
    left_dataset_id: uuid.UUID,
    right_dataset_id: uuid.UUID,
    payload: DatasetStatisticalTestRequest,
    current_user: UserRead,
    storage_backend: Any,
) -> DatasetStatisticalTestResult:
    ensure_owned_project(db, project_id, current_user.id)
    if left_dataset_id == right_dataset_id:
        raise BadRequestError("Cannot run a test comparing a dataset with itself.")

    left = get_dataset_model_for_project(db, project_id, left_dataset_id)
    right = get_dataset_model_for_project(db, project_id, right_dataset_id)

    _validate_column_declared(left, right, payload.column_name.strip())

    left_df = _load_dataframe(left, storage_backend)
    right_df = _load_dataframe(right, storage_backend)

    col_left = _resolve_column(left_df, payload.column_name.strip())
    col_right = _resolve_column(right_df, payload.column_name.strip())

    s_left = left_df[col_left]
    s_right = right_df[col_right]

    if payload.test_type == "welch_t_test":
        raw = welch_t_test(s_left, s_right)
    elif payload.test_type == "proportion_z_test":
        raw = two_proportion_z_test(s_left, s_right)
    elif payload.test_type == "chi_square_distribution":
        raw = chi_square_two_sample_distributions(s_left, s_right)
    else:
        raise BadRequestError("Unsupported test type.")

    return DatasetStatisticalTestResult(
        test_type=payload.test_type,
        column_name=payload.column_name.strip(),
        left_dataset=StatisticalTestDatasetSide(
            id=left.id,
            name=left.name,
            sample_size=int(raw["sample_size_left"]),
        ),
        right_dataset=StatisticalTestDatasetSide(
            id=right.id,
            name=right.name,
            sample_size=int(raw["sample_size_right"]),
        ),
        statistic=raw.get("statistic"),
        p_value=raw.get("p_value"),
        effect_summary=raw.get("effect_summary", ""),
        assumptions_notes=list(raw.get("assumptions_notes", [])),
        interpretation=raw.get("interpretation", ""),
        warnings=list(raw.get("warnings", [])),
        left_mean=raw.get("left_mean"),
        right_mean=raw.get("right_mean"),
        left_proportion=raw.get("left_proportion"),
        right_proportion=raw.get("right_proportion"),
        category_count=raw.get("category_count"),
    )
