from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError
from shared_python.types import parse as parse_type

from service_auth.schemas import UserRead
from service_governance.schemas import ChangeRequestDetail
from service_transformations import coedit
from service_transformations.preview import preview_dataset_transformations
from service_transformations.recipe_suggestions import RecipeSuggestion, suggest_change
from service_transformations.replay import replay_pipeline_run
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.schemas import (
    ReplayResult,
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
from service_transformations import templates as recipe_templates
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

    # --------------------------------------------------------- recipe templates
    #
    # Platform-wide like the tool library: a template is a property of the
    # product, and both calls compute an answer from the columns sent and
    # store nothing.

    @router.get('/transformations/templates', response_model=RecipeTemplateListResponse)
    def get_recipe_templates(
        current_user: UserRead = Depends(get_current_user),
    ) -> RecipeTemplateListResponse:
        return RecipeTemplateListResponse(items=[_template_read(item) for item in recipe_templates.TEMPLATES])

    @router.post('/transformations/templates/match', response_model=RecipeTemplateMatchResponse)
    def post_match_recipe_templates(
        payload: RecipeTemplateColumns,
        current_user: UserRead = Depends(get_current_user),
    ) -> RecipeTemplateMatchResponse:
        """Each template, with the columns it would use here and what it lacks."""
        items = []
        for template in recipe_templates.TEMPLATES:
            mapping, missing = recipe_templates.suggest_mapping(template, payload.columns, payload.types)
            items.append(
                RecipeTemplateMatch(template=_template_read(template), mapping=mapping, missing=missing)
            )
        return RecipeTemplateMatchResponse(items=items)

    @router.post('/transformations/templates/{template_id}/steps', response_model=RecipeTemplateStepsResponse)
    def post_recipe_template_steps(
        template_id: str,
        payload: RecipeTemplateStepsRequest,
        current_user: UserRead = Depends(get_current_user),
    ) -> RecipeTemplateStepsResponse:
        steps = recipe_templates.build_steps(template_id, payload.mapping, payload.columns, payload.types)
        return RecipeTemplateStepsResponse(steps=steps)

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

    @router.post(
        '/projects/{project_id}/runs/{run_id}/replay',
        response_model=ReplayResult,
    )
    def post_replay_pipeline_run(
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend = Depends(_get_storage_backend),
    ) -> ReplayResult:
        """Re-execute a recorded run against its pinned inputs at its recorded
        instant, and compare with what it published. Editor role: it publishes
        a new dataset (central matrix, `replay` ∈ EDITOR_SEGMENTS)."""
        return replay_pipeline_run(
            db,
            project_id=project_id,
            run_id=run_id,
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

    # ---------------------------------------------- editing together (C2)

    @router.get('/projects/{project_id}/pipelines/{pipeline_id}/shared', response_model=coedit.SharedCopyRead)
    def read_recipe_shared_copy(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        epoch: int | None = Query(default=None, ge=1, description="The shared copy's epoch the Studio has."),
        after: int | None = Query(default=None, ge=0, description="The last change the Studio has merged."),
        revision: int | None = Query(default=None, ge=1, description="The saved revision the Studio has."),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> coedit.SharedCopyRead:
        """The recipe's shared working copy, or what changed in it since `after`."""
        return coedit.read_shared(
            db, project_id, pipeline_id, current_user, epoch=epoch, after=after, revision=revision
        )

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/shared', response_model=coedit.SharedCopyPushResult)
    def push_recipe_changes(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: coedit.SharedCopyPush,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> coedit.SharedCopyPushResult:
        """Merge changes into the recipe's shared working copy."""
        return coedit.push_changes(db, project_id, pipeline_id, payload, current_user)

    @router.post(
        '/projects/{project_id}/pipelines/{pipeline_id}/shared/discard', response_model=coedit.SharedCopyRead
    )
    def discard_recipe_changes(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> coedit.SharedCopyRead:
        """Throw away the shared copy's unsaved changes, for everyone editing it."""
        return coedit.discard_unsaved(db, project_id, pipeline_id, current_user)

    @router.post(
        '/projects/{project_id}/pipelines/{pipeline_id}/suggest',
        response_model=ChangeRequestDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def suggest_recipe_change(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: RecipeSuggestion,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ChangeRequestDetail:
        """Suggest a change to a recipe for someone who may edit it to accept or decline."""
        return suggest_change(db, project_id, pipeline_id, payload, current_user)

    return router


class RecipeTemplateRoleRead(BaseModel):
    key: str
    label: str
    description: str
    kind: str
    required: bool
    multiple: bool


class RecipeTemplateRead(BaseModel):
    id: str
    name: str
    description: str
    roles: list[RecipeTemplateRoleRead]


class RecipeTemplateListResponse(BaseModel):
    items: list[RecipeTemplateRead]


class RecipeTemplateColumns(BaseModel):
    columns: list[str] = Field(max_length=2000)
    #: Column name -> type name, as the lineage column listing reports them.
    types: dict[str, str] = Field(default_factory=dict)


class RecipeTemplateMatch(BaseModel):
    template: RecipeTemplateRead
    mapping: dict[str, Any]
    missing: list[str]


class RecipeTemplateMatchResponse(BaseModel):
    items: list[RecipeTemplateMatch]


class RecipeTemplateStepsRequest(RecipeTemplateColumns):
    mapping: dict[str, Any] = Field(default_factory=dict)


class RecipeTemplateStepsResponse(BaseModel):
    steps: list[dict[str, Any]]


def _template_read(template: recipe_templates.Template) -> RecipeTemplateRead:
    return RecipeTemplateRead(
        id=template.id,
        name=template.name,
        description=template.description,
        roles=[
            RecipeTemplateRoleRead(
                key=role.key,
                label=role.label,
                description=role.description,
                kind=role.kind,
                required=role.required,
                multiple=role.multiple,
            )
            for role in template.roles
        ],
    )
