from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_pipeline_runs.contracts import get_pipeline_run_for_project
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError

from service_comparisons.compare_datasets import build_dataset_comparison_summary
from service_comparisons.compare_runs import build_run_comparison_summary
from service_comparisons.schemas import DatasetComparisonSummary, RunComparisonSummary


def get_dataset_comparison_summary(
    db: Session,
    project_id: uuid.UUID,
    left_dataset_id: uuid.UUID,
    right_dataset_id: uuid.UUID,
    current_user: UserRead,
) -> DatasetComparisonSummary:
    ensure_owned_project(db, project_id, current_user.id)
    if left_dataset_id == right_dataset_id:
        raise BadRequestError("Cannot compare a dataset with itself.")
    left = get_dataset_model_for_project(db, project_id, left_dataset_id)
    right = get_dataset_model_for_project(db, project_id, right_dataset_id)
    return build_dataset_comparison_summary(left=left, right=right)


def get_run_comparison_summary(
    db: Session,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: UserRead,
) -> RunComparisonSummary:
    ensure_owned_project(db, project_id, current_user.id)
    run = get_pipeline_run_for_project(db, project_id, run_id)
    return build_run_comparison_summary(run=run)
