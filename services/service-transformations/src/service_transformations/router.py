from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError
from shared_python.types import parse as parse_type

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
    ToolCatalogueResponse,
    ToolPreviewRequest,
    ToolPreviewResponse,
    ToolRead,
)
from service_transformations import tools
from service_transformations.tools import docs as tool_docs
from service_transformations.tools.apply import apply_tool
from service_transformations.service import (
    create_transformation_pipeline,
    get_transformation_pipeline,
    list_transformation_pipelines_for_dataset,
    list_transformation_pipelines_for_project,
    update_transformation_pipeline,
)
from service_transformations.suggestion_schemas import DatasetTransformationSuggestionsResponse
from service_transformations.suggestions import list_dataset_transformation_suggestions


def _json_safe(value: Any) -> Any:
    """Render one cell as something JSON can carry.

    Timestamps, numpy scalars and NaN all survive a DataFrame and none of them
    survive `json.dumps`; returning them would produce a 500 from a preview,
    which is the one endpoint that must never be the thing that breaks.
    """
    if value is None:
        return None
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if np.isnan(number) or np.isinf(number) else number
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


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

    # ------------------------------------------------------------ tool library
    #
    # Not project-scoped: the catalogue is a property of the platform, not of
    # anybody's data, and scoping it would mean the Studio could not populate a
    # command palette until a project was open.

    @router.get('/transformations/tools', response_model=ToolCatalogueResponse)
    def get_tools(
        query: str | None = Query(default=None, max_length=120),
        category: str | None = Query(default=None, max_length=80),
        column_type: str | None = Query(
            default=None, max_length=80,
            description="Return only the tools worth offering on a column of this type.",
        ),
        limit: int = Query(default=500, ge=1, le=1000),
        current_user: UserRead = Depends(get_current_user),
    ) -> ToolCatalogueResponse:
        specs = tools.search(query, limit=limit) if query else list(tools.TOOLS.values())
        if category:
            specs = [spec for spec in specs if spec.category.lower() == category.lower()]
        if column_type:
            try:
                parsed = parse_type(column_type)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                raise BadRequestError(
                    f"{column_type!r} is not a type this platform knows."
                ) from exc
            offered = {spec.name for spec in tools.applicable_to(parsed)}
            specs = [spec for spec in specs if spec.name in offered]

        by_name = {entry["name"]: entry for entry in tool_docs.as_json()}
        return ToolCatalogueResponse(
            categories=tools.categories(),
            items=[ToolRead(**by_name[spec.name]) for spec in specs[:limit]],
        )

    @router.post('/transformations/tools/preview', response_model=ToolPreviewResponse)
    def post_tool_preview(
        payload: ToolPreviewRequest,
        current_user: UserRead = Depends(get_current_user),
    ) -> ToolPreviewResponse:
        """Run one tool over supplied rows, so the UI can show its effect.

        Takes rows in the body rather than reading a dataset: this is what backs
        the live preview beside a tool's settings, where the rows on screen are
        already loaded and a round trip to storage would make every keystroke
        wait for a file read.
        """
        frame = pd.DataFrame(payload.rows)
        if frame.empty and payload.rows:
            frame = pd.DataFrame(payload.rows, columns=list(payload.rows[0]))
        config = {"tool": payload.tool, **payload.params}
        if payload.column:
            config["column"] = payload.column
        if payload.into:
            config["into"] = payload.into
        result, warnings = apply_tool(frame, config)
        return ToolPreviewResponse(
            columns=[str(name) for name in result.columns],
            rows=[
                {str(k): _json_safe(v) for k, v in row.items()}
                for row in result.to_dict(orient="records")
            ],
            warnings=warnings,
        )

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
