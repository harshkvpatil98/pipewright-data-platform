from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_comparisons.schemas import (
    DatasetComparisonSummary,
    DatasetStatisticalTestRequest,
    DatasetStatisticalTestResult,
    RunComparisonSummary,
    SavedStatisticalTestCreate,
    SavedStatisticalTestDetail,
    SavedStatisticalTestListResponse,
    SavedStatisticalTestRead,
    SavedStatisticalTestRunRead,
    SavedStatisticalTestRunsResponse,
    SavedStatisticalTestUpdate,
)
from service_comparisons.saved_tests_service import (
    create_saved_statistical_test,
    get_saved_statistical_test_detail,
    list_saved_statistical_test_runs,
    list_saved_statistical_tests,
    run_saved_statistical_test,
    update_saved_statistical_test,
)
from service_comparisons.service import get_dataset_comparison_summary, get_run_comparison_summary
from service_comparisons.testing_service import run_dataset_statistical_test


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(tags=["comparisons"])

    @router.get(
        "/projects/{project_id}/datasets/{left_dataset_id}/compare/{right_dataset_id}",
        response_model=DatasetComparisonSummary,
    )
    def get_dataset_vs_dataset_comparison(
        project_id: uuid.UUID,
        left_dataset_id: uuid.UUID,
        right_dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetComparisonSummary:
        return get_dataset_comparison_summary(
            db, project_id, left_dataset_id, right_dataset_id, current_user
        )

    @router.post(
        "/projects/{project_id}/datasets/{left_dataset_id}/tests/{right_dataset_id}",
        response_model=DatasetStatisticalTestResult,
    )
    def post_dataset_statistical_test(
        project_id: uuid.UUID,
        left_dataset_id: uuid.UUID,
        right_dataset_id: uuid.UUID,
        payload: DatasetStatisticalTestRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: Any = Depends(get_storage_backend),
    ) -> DatasetStatisticalTestResult:
        return run_dataset_statistical_test(
            db,
            project_id=project_id,
            left_dataset_id=left_dataset_id,
            right_dataset_id=right_dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
        )

    @router.get(
        "/projects/{project_id}/runs/{run_id}/comparison",
        response_model=RunComparisonSummary,
    )
    def get_run_comparison(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RunComparisonSummary:
        return get_run_comparison_summary(db, project_id, run_id, current_user)

    @router.post(
        "/projects/{project_id}/tests/saved",
        response_model=SavedStatisticalTestRead,
    )
    def post_saved_statistical_test(
        project_id: uuid.UUID,
        payload: SavedStatisticalTestCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedStatisticalTestRead:
        return create_saved_statistical_test(db, project_id, payload, current_user)

    @router.get(
        "/projects/{project_id}/tests/saved",
        response_model=SavedStatisticalTestListResponse,
    )
    def get_saved_statistical_tests(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        left_dataset_id: uuid.UUID | None = Query(default=None),
        right_dataset_id: uuid.UUID | None = Query(default=None),
    ) -> SavedStatisticalTestListResponse:
        return list_saved_statistical_tests(
            db,
            project_id,
            current_user,
            left_dataset_id=left_dataset_id,
            right_dataset_id=right_dataset_id,
        )

    @router.get(
        "/projects/{project_id}/tests/saved/{saved_test_id}",
        response_model=SavedStatisticalTestDetail,
    )
    def get_saved_statistical_test(
        project_id: uuid.UUID,
        saved_test_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedStatisticalTestDetail:
        return get_saved_statistical_test_detail(db, project_id, saved_test_id, current_user)

    @router.patch(
        "/projects/{project_id}/tests/saved/{saved_test_id}",
        response_model=SavedStatisticalTestRead,
    )
    def patch_saved_statistical_test(
        project_id: uuid.UUID,
        saved_test_id: uuid.UUID,
        payload: SavedStatisticalTestUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedStatisticalTestRead:
        return update_saved_statistical_test(db, project_id, saved_test_id, payload, current_user)

    @router.post(
        "/projects/{project_id}/tests/saved/{saved_test_id}/run",
        response_model=SavedStatisticalTestRunRead,
    )
    def post_run_saved_statistical_test(
        project_id: uuid.UUID,
        saved_test_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend: Any = Depends(get_storage_backend),
    ) -> SavedStatisticalTestRunRead:
        return run_saved_statistical_test(
            db,
            project_id,
            saved_test_id,
            current_user,
            storage_backend,
        )

    @router.get(
        "/projects/{project_id}/tests/saved/{saved_test_id}/runs",
        response_model=SavedStatisticalTestRunsResponse,
    )
    def get_saved_statistical_test_runs(
        project_id: uuid.UUID,
        saved_test_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedStatisticalTestRunsResponse:
        return list_saved_statistical_test_runs(db, project_id, saved_test_id, current_user)

    return router
