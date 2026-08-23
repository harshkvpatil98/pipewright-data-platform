from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_transformations.models import TransformationPipeline
from service_transformations.steps import ALL_STEP_TYPES
from shared_python.errors import NotFoundError

# Derived from the step registries so a new step cannot be implemented without
# also becoming accepted by validation (and vice versa).
SUPPORTED_TRANSFORMATION_STEP_TYPES = list(ALL_STEP_TYPES)


def get_transformation_pipeline_for_project(db: Session, project_id: uuid.UUID, pipeline_id: uuid.UUID) -> TransformationPipeline:
    pipeline = db.scalar(
        select(TransformationPipeline).where(
            TransformationPipeline.id == pipeline_id,
            TransformationPipeline.project_id == project_id,
        )
    )
    if pipeline is None:
        raise NotFoundError('Transformation pipeline not found.')
    return pipeline


def list_transformation_pipeline_models_for_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> list[TransformationPipeline]:
    return db.scalars(
        select(TransformationPipeline)
        .where(
            TransformationPipeline.project_id == project_id,
            TransformationPipeline.base_dataset_id == dataset_id,
        )
        .order_by(TransformationPipeline.updated_at.desc(), TransformationPipeline.created_at.desc())
    ).all()


def list_transformation_pipeline_models_for_project(db: Session, project_id: uuid.UUID) -> list[TransformationPipeline]:
    return db.scalars(
        select(TransformationPipeline)
        .where(TransformationPipeline.project_id == project_id)
        .order_by(TransformationPipeline.updated_at.desc(), TransformationPipeline.created_at.desc())
    ).all()


def total_transformation_pipelines(db: Session) -> int:
    return db.scalar(select(func.count(TransformationPipeline.id))) or 0
