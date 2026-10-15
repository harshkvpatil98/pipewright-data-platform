from __future__ import annotations

import uuid
from datetime import UTC, datetime

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from service_transformations.contracts import (
    get_transformation_pipeline_for_project,
    list_transformation_pipeline_models_for_dataset,
    list_transformation_pipeline_models_for_project,
)
from service_transformations.coedit import check_save, record_save
from service_transformations.models import TransformationPipeline
from service_transformations.schemas import (
    TransformationPipelineCreate,
    TransformationPipelineListResponse,
    TransformationPipelineRead,
    TransformationPipelineUpdate,
)
from service_transformations.validators import validate_steps_json
from service_transformations.versioning import record_recipe_version
from shared_python.errors import BadRequestError


def _normalize_name(name: str) -> str:
    normalized_name = name.strip()
    if len(normalized_name) < 2:
        raise BadRequestError("Give the recipe a name of at least two characters.")
    return normalized_name


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized_description = description.strip()
    return normalized_description or None


def _serialize_pipeline(pipeline: TransformationPipeline) -> TransformationPipelineRead:
    validated_steps = validate_steps_json(pipeline.steps_json)
    return TransformationPipelineRead(
        id=pipeline.id,
        project_id=pipeline.project_id,
        base_dataset_id=pipeline.base_dataset_id,
        created_by_user_id=pipeline.created_by_user_id,
        name=pipeline.name,
        description=pipeline.description,
        status=pipeline.status,
        steps_json=validated_steps,
        step_count=len(validated_steps),
        output_dataset_id=pipeline.output_dataset_id,
        revision=int(pipeline.revision or 1),
        step_ids=list(pipeline.step_ids_json or []) if len(pipeline.step_ids_json or []) == len(validated_steps) else [],
        revised_at=pipeline.revised_at,
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


def create_transformation_pipeline(
    db,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: TransformationPipelineCreate,
    current_user: UserRead,
) -> TransformationPipelineRead:
    ensure_owned_project(db, project_id, current_user.id)
    get_dataset_model_for_project(db, project_id, dataset_id)
    validated_steps = validate_steps_json(payload.steps_json)

    pipeline = TransformationPipeline(
        project_id=project_id,
        base_dataset_id=dataset_id,
        created_by_user_id=current_user.id,
        name=_normalize_name(payload.name),
        description=_normalize_description(payload.description),
        status=payload.status,
        steps_json=[step.model_dump(mode="json") for step in validated_steps],
        revision=1,
        step_ids_json=[uuid.uuid4().hex for _ in validated_steps],
        revised_by_user_id=current_user.id,
        revised_at=datetime.now(UTC),
    )
    db.add(pipeline)
    db.flush()
    record_recipe_version(db, pipeline, current_user.id)
    db.commit()
    db.refresh(pipeline)
    return _serialize_pipeline(pipeline)


def list_transformation_pipelines_for_dataset(
    db,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
) -> TransformationPipelineListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    get_dataset_model_for_project(db, project_id, dataset_id)
    pipelines = list_transformation_pipeline_models_for_dataset(db, project_id, dataset_id)
    return TransformationPipelineListResponse(items=[_serialize_pipeline(item) for item in pipelines])


def list_transformation_pipelines_for_project(
    db,
    *,
    project_id: uuid.UUID,
    current_user: UserRead,
) -> TransformationPipelineListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    pipelines = list_transformation_pipeline_models_for_project(db, project_id)
    return TransformationPipelineListResponse(items=[_serialize_pipeline(item) for item in pipelines])


def get_transformation_pipeline(
    db,
    *,
    project_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    current_user: UserRead,
) -> TransformationPipelineRead:
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    return _serialize_pipeline(pipeline)


def update_transformation_pipeline(
    db,
    *,
    project_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    payload: TransformationPipelineUpdate,
    current_user: UserRead,
) -> TransformationPipelineRead:
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    get_dataset_model_for_project(db, project_id, pipeline.base_dataset_id)
    # A save that names the revision it started from is refused when someone
    # saved since, rather than written over their changes (C2).
    check_save(db, pipeline, expected_revision=payload.expected_revision)

    before = (pipeline.name, pipeline.description, list(pipeline.steps_json or []))
    if payload.name is not None:
        pipeline.name = _normalize_name(payload.name)
    if payload.description is not None:
        pipeline.description = _normalize_description(payload.description)
    if payload.status is not None:
        pipeline.status = payload.status
    if payload.steps_json is not None:
        validated_steps = validate_steps_json(payload.steps_json)
        pipeline.steps_json = [step.model_dump(mode="json") for step in validated_steps]

    if (pipeline.name, pipeline.description, list(pipeline.steps_json or [])) != before or (
        payload.step_ids is not None and payload.step_ids != list(pipeline.step_ids_json or [])
    ):
        record_save(
            db,
            pipeline,
            current_user,
            step_ids=payload.step_ids,
            from_shared_epoch=payload.shared_epoch,
        )
        db.flush()
        record_recipe_version(db, pipeline, current_user.id)
    db.commit()
    db.refresh(pipeline)
    return _serialize_pipeline(pipeline)
