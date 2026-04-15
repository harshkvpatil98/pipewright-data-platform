from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_transformations.preview import preview_dataset_transformations
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import (
    TransformationPipelineCreate,
    TransformationPipelineListResponse,
    TransformationPipelineRead,
    TransformationPreviewRequest,
    TransformationPreviewResponse,
    TransformationPipelineUpdate,
    TransformationRunResponse,
)
from service_transformations.service import (
    create_transformation_pipeline,
    get_transformation_pipeline,
    list_transformation_pipelines_for_dataset,
    list_transformation_pipelines_for_project,
    update_transformation_pipeline,
)
from service_transformations.suggestion_schemas import DatasetTransformationSuggestionsResponse
from service_transformations.suggestions import list_dataset_transformation_suggestions


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., Any] | None = None,
    settings: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=['transformations'])

    def _get_storage_backend():
        if get_storage_backend is None:
            raise RuntimeError("Storage backend dependency is required for transformation preview.")
        return get_storage_backend()

    @router.get('/projects/{project_id}/pipelines', response_model=TransformationPipelineListResponse)
    def get_project_pipelines(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineListResponse:
        return list_transformation_pipelines_for_project(db, project_id=project_id, current_user=current_user)

    @router.post(
        '/projects/{project_id}/datasets/{dataset_id}/pipelines',
        response_model=TransformationPipelineRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_dataset_pipeline(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: TransformationPipelineCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineRead:
        return create_transformation_pipeline(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=payload,
            current_user=current_user,
        )

    @router.post(
        '/projects/{project_id}/datasets/{dataset_id}/pipelines/preview',
        response_model=TransformationPreviewResponse,
    )
    def post_dataset_pipeline_preview(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        payload: TransformationPreviewRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(_get_storage_backend),
    ) -> TransformationPreviewResponse:
        return preview_dataset_transformations(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    @router.get('/projects/{project_id}/datasets/{dataset_id}/pipelines', response_model=TransformationPipelineListResponse)
    def get_dataset_pipelines(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineListResponse:
        return list_transformation_pipelines_for_dataset(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            current_user=current_user,
        )

    @router.get(
        '/projects/{project_id}/datasets/{dataset_id}/suggestions',
        response_model=DatasetTransformationSuggestionsResponse,
    )
    def get_dataset_transformation_suggestions(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetTransformationSuggestionsResponse:
        return list_dataset_transformation_suggestions(
            db,
            project_id=project_id,
            dataset_id=dataset_id,
            current_user=current_user,
        )

    @router.post(
        '/projects/{project_id}/pipelines/{pipeline_id}/run',
        response_model=TransformationRunResponse,
    )
    def post_run_transformation_pipeline(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(_get_storage_backend),
    ) -> TransformationRunResponse:
        return run_saved_transformation_pipeline(
            db,
            project_id=project_id,
            pipeline_id=pipeline_id,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    @router.get('/projects/{project_id}/pipelines/{pipeline_id}', response_model=TransformationPipelineRead)
    def get_project_pipeline(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineRead:
        return get_transformation_pipeline(db, project_id=project_id, pipeline_id=pipeline_id, current_user=current_user)

    @router.patch('/projects/{project_id}/pipelines/{pipeline_id}', response_model=TransformationPipelineRead)
    def patch_project_pipeline(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: TransformationPipelineUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineRead:
        return update_transformation_pipeline(
            db,
            project_id=project_id,
            pipeline_id=pipeline_id,
            payload=payload,
            current_user=current_user,
        )

    return router
