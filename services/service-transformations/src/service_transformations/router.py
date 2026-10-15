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
from service_transformations import recipe_management as manage
from service_transformations.schemas import (
    IncrementalSettings,
    ReplayResult,
    TransformationPipelineCreate,
    TransformationPipelineListResponse,
    TransformationPipelineRead,
    TransformationPreviewRequest,
    TransformationRunRequest,
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
    set_incremental,
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


class RegexTestRequest(BaseModel):
    pattern: str = Field(max_length=2000)
    values: list[str] = Field(default_factory=list, max_length=50)
    replacement: str | None = Field(default=None, max_length=2000)


class RegexTestResult(BaseModel):
    value: str
    matched: bool
    spans: list[list[int]]
    groups: list[str]
    replaced: str | None


class RegexTestResponse(BaseModel):
    valid: bool
    error: str | None
    results: list[RegexTestResult]


class TokenRevealRequest(BaseModel):
    token: str = Field(min_length=5, max_length=10_000)
    key_name: str = Field(default="default", min_length=1, max_length=100)


class TokenRevealResponse(BaseModel):
    value: str


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

    @router.put(
        '/projects/{project_id}/pipelines/{pipeline_id}/incremental',
        response_model=TransformationPipelineRead,
    )
    def put_incremental(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: IncrementalSettings,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> TransformationPipelineRead:
        """How the recipe's runs compute: every row, only rows added since the last run, or
        only the partitions whose rows changed. Each falls back to a full run, and says why."""
        return set_incremental(db, project_id=project_id, pipeline_id=pipeline_id, settings=payload,
                               current_user=current_user)

    @router.post(
        '/projects/{project_id}/pipelines/{pipeline_id}/run',
        response_model=TransformationRunResponse,
    )
    def post_run_transformation_pipeline(
        project_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: TransformationRunRequest | None = None,
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
            parameters=payload.parameters if payload is not None else None,
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

    # ------------------------------------------------------ the regex tester (E1)

    @router.post('/transformations/tools/regex/test', response_model=RegexTestResponse)
    def post_regex_test(payload: RegexTestRequest,
                        current_user: UserRead = Depends(get_current_user)) -> RegexTestResponse:
        """Try a pattern on sample values with the engine's own regular expressions (Python's), which
        differ from a browser's in places (named groups, lookbehind), so the Studio asks here."""
        import re

        try:
            pattern = re.compile(payload.pattern)
        except re.error as exc:
            return RegexTestResponse(valid=False, error=f"That pattern will not compile: {exc}.", results=[])
        results = []
        for value in payload.values[:50]:
            text = value[:500]
            matches = list(pattern.finditer(text))
            first = matches[0] if matches else None
            results.append(RegexTestResult(
                value=text, matched=bool(matches), spans=[[m.start(), m.end()] for m in matches[:20]],
                groups=[g if g is not None else "" for g in first.groups()] if first else [],
                replaced=pattern.sub(payload.replacement, text) if payload.replacement is not None else None,
            ))
        return RegexTestResponse(valid=True, error=None, results=results)

    # --------------------------------------------- revealing a reversible token (E1)

    @router.post('/transformations/tokens/reveal', response_model=TokenRevealResponse)
    def post_token_reveal(payload: TokenRevealRequest,
                          current_user: UserRead = Depends(get_current_user)) -> TokenRevealResponse:
        """Turn a reversible token back into its value. A deployment administrator only; the request is
        in the audit log like every write."""
        from shared_python.errors import ForbiddenError
        from shared_python.security.reversible_tokens import reveal

        if current_user.role != "admin":
            raise ForbiddenError("Only an administrator of this deployment can reveal a token.")
        return TokenRevealResponse(value=reveal(payload.token, payload.key_name))

    # ------------------------------------------------------ managing recipes (E1)

    @router.put('/projects/{project_id}/pipelines/{pipeline_id}/parameters', response_model=TransformationPipelineRead)
    def put_recipe_parameters(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.ParametersUpdate,
                              db: Session = Depends(get_db),
                              current_user: UserRead = Depends(get_current_user)) -> TransformationPipelineRead:
        from service_transformations.service import _serialize_pipeline

        return _serialize_pipeline(manage.set_parameters(db, project_id=project_id, pipeline_id=pipeline_id,
                                                         payload=payload, current_user=current_user))

    @router.get('/projects/{project_id}/recipe-templates', response_model=manage.TemplateListResponse)
    def get_saved_templates(project_id: uuid.UUID, db: Session = Depends(get_db),
                            current_user: UserRead = Depends(get_current_user)) -> manage.TemplateListResponse:
        return manage.list_templates(db, project_id=project_id, current_user=current_user)

    @router.post('/projects/{project_id}/recipe-templates', response_model=manage.TemplateRead,
                 status_code=status.HTTP_201_CREATED)
    def post_saved_template(project_id: uuid.UUID, payload: manage.TemplateCreate, db: Session = Depends(get_db),
                            current_user: UserRead = Depends(get_current_user)) -> manage.TemplateRead:
        return manage.create_template(db, project_id=project_id, payload=payload, current_user=current_user)

    @router.delete('/projects/{project_id}/recipe-templates/{template_id}', status_code=status.HTTP_204_NO_CONTENT)
    def delete_saved_template(project_id: uuid.UUID, template_id: uuid.UUID, db: Session = Depends(get_db),
                              current_user: UserRead = Depends(get_current_user)) -> None:
        manage.delete_template(db, project_id=project_id, template_id=template_id, current_user=current_user)

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/branch', response_model=TransformationPipelineRead,
                 status_code=status.HTTP_201_CREATED)
    def post_branch(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.BranchCreate,
                    db: Session = Depends(get_db),
                    current_user: UserRead = Depends(get_current_user)) -> TransformationPipelineRead:
        from service_transformations.service import _serialize_pipeline

        return _serialize_pipeline(manage.branch(db, project_id=project_id, pipeline_id=pipeline_id, payload=payload,
                                                 current_user=current_user))

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/merge', response_model=manage.MergeResult)
    def post_merge(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.MergeRequest,
                   db: Session = Depends(get_db),
                   current_user: UserRead = Depends(get_current_user)) -> manage.MergeResult:
        return manage.merge(db, project_id=project_id, branch_id=pipeline_id, payload=payload,
                            current_user=current_user)

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/merge/preview', response_model=manage.MergeResult)
    def post_merge_preview(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.MergeRequest,
                           db: Session = Depends(get_db),
                           current_user: UserRead = Depends(get_current_user)) -> manage.MergeResult:
        """What merging would do, and what conflicts, without merging."""
        return manage.merge(db, project_id=project_id, branch_id=pipeline_id, payload=payload,
                            current_user=current_user, preview=True)

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/copy', response_model=manage.CopyResult,
                 status_code=status.HTTP_201_CREATED)
    def post_copy(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.CopyRequest,
                  db: Session = Depends(get_db),
                  current_user: UserRead = Depends(get_current_user)) -> manage.CopyResult:
        return manage.copy_to(db, project_id=project_id, pipeline_id=pipeline_id, payload=payload,
                              current_user=current_user)

    @router.post('/projects/{project_id}/pipelines/{pipeline_id}/split', response_model=manage.SplitResult,
                 status_code=status.HTTP_201_CREATED)
    def post_split(project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: manage.SplitRequest,
                   db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user),
                   storage_backend = Depends(_get_storage_backend)) -> manage.SplitResult:
        return manage.split(db, project_id=project_id, pipeline_id=pipeline_id, payload=payload,
                            current_user=current_user, storage_backend=storage_backend)

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
